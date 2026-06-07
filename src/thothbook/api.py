"""Serveur web de Thothbook (FastAPI), multi-utilisateur.

Réutilise la même logique que la CLI (graphe / llm / conseil), mais l'expose en
endpoints HTTP. Chaque route data est sous /api et exige un jeton Firebase valide
(en-tête Authorization: Bearer <idToken>) : on en déduit l'UID et on cloisonne
toutes les données par utilisateur. Les appels LLM sont facturés à l'usage (crédits).

Routage (Firebase Hosting redirige /api/** vers ce backend sur Cloud Run) :
    GET  /               -> la page web (dev local ; en prod c'est Hosting qui la sert)
    GET  /api/solde      -> solde de crédits entiers de l'utilisateur
    GET  /api/etat       -> objectifs + tâches en cours (pour l'en-tête)
    GET  /api/agenda     -> événements planifiés (calendrier)
    GET  /api/paiements/offres   -> packs de recharge
    POST /api/paiements/checkout -> session Stripe Checkout authentifiée
    POST /api/paiements/webhook  -> confirmation Stripe (sans Firebase, via signature)
    POST /api/suggestions-> suggestions PROACTIVES (appel LLM, facturé)
    POST /api/chat       -> clarification au clavier (appel LLM, facturé)
    POST /api/ajuster    -> ajustement ciblé d'une carte (appel LLM, facturé)
    POST /api/valider    -> applique les actions d'une suggestion -> écrit dans le graphe
"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from .auth import utilisateur_courant
from .config import ROOT, charger_config
from .conseil import generer_reponse
from .credits import facturer_appel
from .graphe import Graphe
from .llm import construire_modele
from .paiement import (
    PackInconnuErreur,
    PaiementConfigurationErreur,
    PaiementErreur,
    construire_evenement_webhook,
    creer_session_checkout,
    offres_paiement,
    traiter_evenement_stripe,
)
from .schemas import Reponse, Suggestion

# Initialisé une fois au démarrage du serveur.
_cfg = charger_config()
_graphe: "Graphe | None" = None
_modele = construire_modele(_cfg)
_nom_modele = _cfg["llm"]["model"]
_credits_par_euro = int(_cfg.get("credits", {}).get("par_euro", 100) or 100)
_offert = int(_cfg.get("credits", {}).get("offert_inscription", 0) or 0)

# Mémoire de conversation PAR utilisateur (en mémoire process ; voir limites du plan).
_historiques: dict[str, list] = {}


def _get_graphe() -> "Graphe":
    """Connexion lazy à Neo4j : créée au premier appel, pas à l'import.
    Permet au container Cloud Run de démarrer et écouter sur le port
    même si Neo4j est temporairement injoignable."""
    global _graphe
    if _graphe is None:
        _graphe = Graphe(_cfg["neo4j"]["uri"], _cfg["neo4j"]["user"], _cfg["neo4j"]["password"])
    return _graphe


app = FastAPI(title="Thothbook")
api = APIRouter(prefix="/api")

PROMPT_PROACTIF = (
    "Sans que je te pose de question, regarde mon graphe (objectifs, tâches, habitudes, "
    "agenda) et la date ET L'HEURE actuelles, puis propose-moi 1 à 3 actions concrètes à "
    "planifier bientôt. PRIORITÉ : si j'ai des « Tâches EN COURS » (entamées, pas finies), "
    "propose d'abord de les REPRENDRE à un NOUVEAU créneau dans le futur (action planifier, "
    "jamais une date passée), AVANT toute nouvelle tâche. Ensuite : avancer vers mes "
    "objectifs, planifier mes habitudes dues (horizon glissant) et trouver un créneau à mes "
    "tâches en réserve (même sans objectif). N'utilise JAMAIS une date/heure déjà écoulée. "
    "Sois bref."
)

_JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _maintenant_fr() -> str:
    """Date ET heure courantes en français (l'heure est cruciale : sinon le LLM propose des
    créneaux déjà passés faute de savoir quelle heure il est)."""
    n = datetime.now()
    return f"{_JOURS_FR[n.weekday()]} {n.day} {_MOIS_FR[n.month - 1]} {n.year}, {n:%H:%M}"


def uid_courant(u: dict = Depends(utilisateur_courant)) -> str:
    """Vérifie le jeton, garantit l'existence de l'utilisateur et renvoie son UID."""
    _get_graphe().assurer_utilisateur(u["uid"], u.get("email"), _offert, _credits_par_euro)
    return u["uid"]


def _exiger_credits(uid: str) -> None:
    """Garde avant un appel LLM : solde épuisé -> 402 (le front propose de recharger)."""
    if _get_graphe().solde(uid) <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Crédits épuisés. Recharge pour continuer à utiliser Thothbook.",
        )


def _repondre(uid: str, message_utilisateur: str) -> Reponse:
    """Un tour de conversation : ajoute le message, interroge le LLM, facture, renvoie la réponse."""
    historique = _historiques.setdefault(uid, [])
    historique.append(HumanMessage(content=message_utilisateur))
    contexte = _get_graphe().lire_contexte(uid)
    reponse, usage = generer_reponse(_modele, contexte, historique, _maintenant_fr())
    facturer_appel(_cfg, _get_graphe(), uid, _nom_modele, usage)
    historique.append(AIMessage(content=reponse.message))
    return reponse


def _base_url_publique(request: Request) -> str:
    """URL publique utilisée pour les retours Stripe (success/cancel).

    Priorité:
    1) APP_BASE_URL (forcé en prod pour éviter les retours sur run.app)
    2) Origin du navigateur
    3) base_url FastAPI
    """
    forcee = (os.environ.get("APP_BASE_URL") or "").strip()
    if forcee:
        return forcee.rstrip("/")

    origin = (request.headers.get("origin") or "").strip()
    if origin.startswith("http://") or origin.startswith("https://"):
        return origin.rstrip("/")

    return str(request.base_url).rstrip("/")


@app.get("/")
def index() -> FileResponse:
    # En prod, Firebase Hosting sert ce fichier ; utile pour le dev local (uvicorn).
    return FileResponse(ROOT / "web" / "index.html")


@api.get("/solde")
def solde(uid: str = Depends(uid_courant)) -> dict:
    return {"solde": _get_graphe().solde(uid), "unite": "credits"}


@api.get("/paiements/offres")
def paiements_offres(uid: str = Depends(uid_courant)) -> dict:
    del uid
    return offres_paiement(_cfg)


class CheckoutRequest(BaseModel):
    pack_id: str


@api.post("/paiements/checkout")
def paiements_checkout(
    req: CheckoutRequest,
    request: Request,
    utilisateur: dict = Depends(utilisateur_courant),
) -> dict:
    _get_graphe().assurer_utilisateur(utilisateur["uid"], utilisateur.get("email"), _offert, _credits_par_euro)
    try:
        return creer_session_checkout(
            _cfg,
            base_url=_base_url_publique(request),
            uid=utilisateur["uid"],
            email=utilisateur.get("email"),
            pack_id=req.pack_id,
        )
    except PackInconnuErreur as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PaiementConfigurationErreur as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@api.post("/paiements/webhook")
async def paiements_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")) -> dict:
    payload = await request.body()
    try:
        event = construire_evenement_webhook(payload, stripe_signature)
        return traiter_evenement_stripe(_cfg, _get_graphe(), event, _credits_par_euro)
    except PaiementConfigurationErreur as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except PaiementErreur as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@api.get("/etat")
def etat(uid: str = Depends(uid_courant)) -> dict:
    return _get_graphe().lire_etat(uid)


@api.get("/agenda")
def agenda(uid: str = Depends(uid_courant)) -> list:
    return _get_graphe().lire_agenda(uid)


class SuggestionsRequest(BaseModel):
    exclure: list[str] = []  # titres de suggestions écartées (« Plus tard ») à ne pas répéter


@api.post("/suggestions", response_model=Reponse)
def suggestions(req: SuggestionsRequest = SuggestionsRequest(), uid: str = Depends(uid_courant)) -> Reponse:
    _exiger_credits(uid)
    # Les suggestions proactives sont pilotées par l'ÉTAT DU GRAPHE, pas par la
    # conversation. On repart d'un historique vierge : sinon le LLM, amorcé par ses
    # propres suggestions précédentes, repropose une tâche qu'on vient de valider —
    # alors que le graphe, lui, est déjà à jour (d'où le « ça se corrige en recliquant »).
    # La clarification « Ajuster » (/ajuster) garde, elle, le contexte du tour en cours.
    _historiques[uid] = []
    prompt = PROMPT_PROACTIF
    if req.exclure:
        # « Plus tard » a une mémoire : on dit explicitement au LLM de ne pas répéter ces
        # suggestions-là (sinon il les régénère à l'identique depuis le même graphe).
        items = " ; ".join(req.exclure[-8:])
        prompt += (
            f"\n\nJe viens d'écarter ces suggestions (« plus tard ») — ne me les repropose "
            f"PAS à l'identique, propose autre chose : {items}."
        )
    return _repondre(uid, prompt)


class ChatRequest(BaseModel):
    message: str


@api.post("/chat", response_model=Reponse)
def chat(req: ChatRequest, uid: str = Depends(uid_courant)) -> Reponse:
    _exiger_credits(uid)
    return _repondre(uid, req.message)


class AjusterRequest(BaseModel):
    suggestion: Suggestion  # la suggestion à ajuster
    message: str            # ce que l'utilisateur veut changer


@api.post("/ajuster", response_model=Reponse)
def ajuster(req: AjusterRequest, uid: str = Depends(uid_courant)) -> Reponse:
    _exiger_credits(uid)
    # Ajustement CIBLÉ d'UNE carte : on ne touche pas l'historique global (sinon ça
    # polluerait les suggestions proactives) et on demande au LLM de reproposer une
    # seule suggestion, corrigée. Le front ne remplace que cette carte.
    acts = ", ".join(a.type for a in req.suggestion.actions) or "aucune"
    consigne = (
        f"Tu m'avais proposé cette suggestion :\n"
        f"- Titre : {req.suggestion.titre}\n"
        f"- Pourquoi : {req.suggestion.pourquoi}\n"
        f"- Quand : {req.suggestion.quand or '(non daté)'}\n"
        f"- Actions : {acts}\n"
        f"Je veux l'AJUSTER : « {req.message} ».\n"
        f"Repropose UNIQUEMENT cette suggestion (une seule), corrigée selon ma demande, "
        f"avec ses actions à jour. Ne propose rien d'autre."
    )
    contexte = _get_graphe().lire_contexte(uid)
    reponse, usage = generer_reponse(_modele, contexte, [HumanMessage(content=consigne)], _maintenant_fr())
    facturer_appel(_cfg, _get_graphe(), uid, _nom_modele, usage)
    return reponse


@api.post("/valider")
def valider(suggestion: Suggestion, uid: str = Depends(uid_courant)) -> dict:
    try:
        appliquees = [_get_graphe().appliquer_action(uid, a.model_dump()) for a in suggestion.actions]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _historiques.setdefault(uid, []).append(HumanMessage(content=f"[J'ai validé : {suggestion.titre}]"))
    return {"ok": True, "appliquees": appliquees, "stats": _get_graphe().stats(uid)}


app.include_router(api)
