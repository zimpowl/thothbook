"""Accès au graphe Neo4j : connexion, lecture du contexte, écriture des actions.

Multi-utilisateur : il n'y a plus d'ancre globale `:Moi`. Chaque utilisateur est
un nœud `(:Utilisateur {uid})` (uid = UID Firebase), et **toutes** les données qu'il
possède portent une propriété `uid` ET sont reliées à lui. Toute requête est scopée
par `uid` : c'est l'invariant d'isolation. Aucune donnée ne fuit d'un compte à l'autre,
même si une relation était mal écrite (la clé `uid` du nœud le garantit).

Modèle de données (par utilisateur) :
    (:Utilisateur)-[:VISE]->(:Objectif)
    (:Utilisateur)-[:DOIT_FAIRE]->(:Tache)-[:SERT]->(:Objectif)
    (:Utilisateur)-[:PRATIQUE]->(:Habitude)-[:SERT]->(:Objectif)
    (:Utilisateur)-[:CONNAIT]->(:Personne)
    (:Utilisateur)-[:A_CONSOMME]->(:Usage)  # journal de consommation LLM (crédits)

    (:Sortie)-[:AVEC]->(:Personne)
    (:Sortie)-[:SERT|:CONTRARIE]->(:Objectif)
    (:Tache|:Sortie|:Habitude)-[:PLANIFIE_A]->(:Creneau)  # le Creneau porte un statut par occurrence
"""

import json
from datetime import date, datetime

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError


def _est_passe(debut: str | None, fin: str | None) -> bool:
    """Le créneau est-il déjà passé ? Compare par jour si pas d'heure, sinon par datetime."""
    ref = fin or debut
    if not ref:
        return False
    try:
        if len(ref) <= 10:  # date seule (YYYY-MM-DD) -> passé seulement si jour révolu
            return date.fromisoformat(ref[:10]) < datetime.now().date()
        return datetime.fromisoformat(ref) < datetime.now()
    except ValueError:
        return False


def _statut_agenda(debut: str | None, fin: str | None, statut: str | None, kind: str | None = None) -> str:
    """Statut d'une OCCURRENCE pour la couleur du calendrier, piloté par l'occurrence elle-même
    (créneau OU sortie), plus par la tâche parente :
    'fait' (vert, révisé OK) / 'a_venir' (bleu, futur) / 'a_revoir' (ambre, passé pas encore revu)."""
    if statut == "fait":
        return "fait"
    return "a_revoir" if _est_passe(debut, fin) else "a_venir"


class Graphe:
    def __init__(self, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        # Bookmarks de la dernière session : on les rejoue à la session suivante pour
        # garantir le "read-your-own-writes" sur un cluster Aura (sinon une relecture peut
        # tomber sur un membre qui n'a pas encore reçu l'écriture précédente).
        self._bookmarks = None
        self._assurer_schema()

    def fermer(self) -> None:
        self._driver.close()

    def _executer(self, cypher: str, **params) -> list[dict]:
        with self._driver.session(bookmarks=self._bookmarks) as session:
            data = session.run(cypher, **params).data()
            self._bookmarks = session.last_bookmarks()
            return data

    def _assurer_schema(self) -> None:
        """Contrainte d'unicité sur l'utilisateur + index par uid sur les labels chauds.
        Idempotent (IF NOT EXISTS) : sans danger à chaque démarrage."""
        self._executer(
            "CREATE CONSTRAINT utilisateur_uid IF NOT EXISTS "
            "FOR (u:Utilisateur) REQUIRE u.uid IS UNIQUE"
        )
        self._executer(
            "CREATE CONSTRAINT recharge_provider_ref IF NOT EXISTS "
            "FOR (r:Recharge) REQUIRE r.provider_ref IS UNIQUE"
        )
        for label in ("Objectif", "Tache", "Habitude", "Personne", "Creneau", "Sortie"):
            self._executer(
                f"CREATE INDEX {label.lower()}_uid IF NOT EXISTS FOR (n:{label}) ON (n.uid)"
            )

    # ------------------------------------------------------------------ #
    # UTILISATEUR & CRÉDITS
    # ------------------------------------------------------------------ #
    def assurer_utilisateur(
        self, uid: str, email: str | None = None, offert: int = 0, credits_par_euro: int = 100
    ) -> None:
        """MERGE l'utilisateur et migre l'ancien solde euro -> crédits entiers une seule fois."""
        self._executer(
            "MERGE (u:Utilisateur {uid:$uid}) "
            "ON CREATE SET u.email = $email, u.credits = $offert, u.credits_version = 2, u.cree_le = datetime() "
            "ON MATCH SET u.email = coalesce($email, u.email), "
            "u.credits = CASE "
            "  WHEN coalesce(u.credits_version, 1) < 2 THEN toInteger(round(coalesce(u.credits, 0.0) * $credits_par_euro)) "
            "  ELSE toInteger(round(coalesce(u.credits, 0))) "
            "END, "
            "u.credits_version = 2",
            uid=uid,
            email=email,
            offert=offert,
            credits_par_euro=credits_par_euro,
        )

    def solde(self, uid: str) -> int:
        rows = self._executer(
            "MATCH (u:Utilisateur {uid:$uid}) RETURN toInteger(round(coalesce(u.credits, 0))) AS solde",
            uid=uid,
        )
        return int(rows[0]["solde"]) if rows else 0

    def debiter(self, uid: str, montant: int) -> int:
        montant = max(0, int(montant or 0))
        rows = self._executer(
            "MATCH (u:Utilisateur {uid:$uid}) "
            "SET u.credits = CASE "
            "  WHEN toInteger(round(coalesce(u.credits, 0))) <= $montant THEN 0 "
            "  ELSE toInteger(round(coalesce(u.credits, 0))) - $montant "
            "END "
            "RETURN u.credits AS solde",
            uid=uid,
            montant=montant,
        )
        return int(rows[0]["solde"]) if rows else 0

    def crediter(self, uid: str, montant: int, source: str = "manuel") -> int:
        """Ajoute des crédits manuellement."""
        montant = max(0, int(montant or 0))
        rows = self._executer(
            "MATCH (u:Utilisateur {uid:$uid}) "
            "SET u.credits = toInteger(round(coalesce(u.credits, 0))) + $montant "
            "CREATE (u)-[:A_RECHARGE]->(:Recharge {"
            "  date:datetime(), montant:$montant, source:$source, uid:$uid, provider:'manuel', provider_ref:randomUUID()"
            "}) "
            "RETURN u.credits AS solde",
            uid=uid,
            montant=montant,
            source=source,
        )
        return int(rows[0]["solde"]) if rows else 0

    def crediter_recharge_externe(
        self,
        uid: str,
        montant: int,
        provider: str,
        reference: str,
        source: str = "externe",
        brut_centimes: int | None = None,
        meta: dict | None = None,
    ) -> dict:
        """Crédite une recharge externe de manière idempotente (webhook Stripe)."""
        montant = max(0, int(montant or 0))
        provider_ref = f"{provider}:{reference}"
        meta_json = json.dumps(meta or {}, ensure_ascii=False, sort_keys=True)
        try:
            with self._driver.session(bookmarks=self._bookmarks) as session:
                rows = session.run(
                    "MATCH (u:Utilisateur {uid:$uid}) "
                    "SET u.credits = toInteger(round(coalesce(u.credits, 0))) + $montant "
                    "CREATE (r:Recharge {"
                    "  provider_ref:$provider_ref, provider:$provider, reference:$reference, uid:$uid, "
                    "  date:datetime(), montant:$montant, source:$source, brut_centimes:$brut_centimes, meta_json:$meta_json"
                    "}) "
                    "CREATE (u)-[:A_RECHARGE]->(r) "
                    "RETURN u.credits AS solde",
                    uid=uid,
                    montant=montant,
                    provider_ref=provider_ref,
                    provider=provider,
                    reference=reference,
                    source=source,
                    brut_centimes=brut_centimes,
                    meta_json=meta_json,
                ).data()
                self._bookmarks = session.last_bookmarks()
            return {"applique": True, "solde": int(rows[0]["solde"]) if rows else self.solde(uid)}
        except Neo4jError as exc:
            if exc.code == "Neo.ClientError.Schema.ConstraintValidationFailed":
                return {"applique": False, "solde": self.solde(uid)}
            raise

    def journaliser_usage(
        self, uid: str, modele: str, tokens_in: int, tokens_out: int, cout_reel_eur: float, credits_factures: int
    ) -> None:
        self._executer(
            "MATCH (u:Utilisateur {uid:$uid}) "
            "CREATE (u)-[:A_CONSOMME]->(:Usage {"
            "  date:datetime(), modele:$modele, tokens_in:$tin, tokens_out:$tout,"
            "  cout_reel_eur:$cout, credits_factures:$prix})",
            uid=uid,
            modele=modele,
            tin=tokens_in,
            tout=tokens_out,
            cout=cout_reel_eur,
            prix=credits_factures,
        )

    # ------------------------------------------------------------------ #
    # LECTURE : on assemble un résumé texte de "ta vie" pour le LLM.
    # ------------------------------------------------------------------ #
    def lire_contexte(self, uid: str) -> str:
        objectifs = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:VISE]->(o:Objectif) "
            "WHERE coalesce(o.statut,'actif') = 'actif' "
            "RETURN DISTINCT o.nom AS nom, coalesce(o.priorite,'moyenne') AS priorite, "
            "coalesce(o.statut,'actif') AS statut",
            uid=uid,
        )
        maintenant = datetime.now().isoformat(timespec="minutes")
        taches = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(t:Tache) "
            "WHERE coalesce(t.statut,'a_faire') = 'a_faire' "
            # On exclut les tâches DÉJÀ planifiées (créneau futur) : elles vivent dans l'agenda,
            # inutile de proposer de les re-planifier (corrige « propose de planifier X dans 1h »).
            "AND size([(t)-[:PLANIFIE_A]->(c:Creneau) WHERE c.debut > $now | 1]) = 0 "
            "OPTIONAL MATCH (t)-[:SERT]->(o:Objectif) "
            "RETURN DISTINCT t.nom AS nom, coalesce(t.urgence,'moyenne') AS urgence, o.nom AS sert",
            uid=uid,
            now=maintenant,
        )
        en_cours = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(t:Tache) WHERE t.statut = 'en_cours' "
            "OPTIONAL MATCH (t)-[:SERT]->(o:Objectif) "
            "RETURN DISTINCT t.nom AS nom, o.nom AS sert, "
            "[(t)-[:PLANIFIE_A]->(c:Creneau) WHERE c.debut IS NOT NULL | c.debut] AS creneaux",
            uid=uid,
        )
        habitudes = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:PRATIQUE]->(h:Habitude) "
            "WHERE coalesce(h.statut,'active') = 'active' "
            "RETURN h.nom AS nom, coalesce(h.frequence,'?') AS frequence, "
            "[(h)-[:PLANIFIE_A]->(c:Creneau) WHERE c.debut IS NOT NULL | c.debut] AS seances",
            uid=uid,
        )
        personnes = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:CONNAIT]->(p:Personne) RETURN p.nom AS nom", uid=uid
        )
        planifie = self._executer(
            "MATCH (c:Creneau {uid:$uid}) WHERE c.debut IS NOT NULL "
            "OPTIONAL MATCH (x)-[:PLANIFIE_A]->(c) "
            "RETURN coalesce(c.libelle, x.nom, '(activité)') AS nom, "
            "c.debut AS debut, c.fin AS fin, coalesce(c.statut,'a_venir') AS statut "
            "ORDER BY c.debut",
            uid=uid,
        )

        lignes: list[str] = []

        def section(titre: str, items: list[str]) -> None:
            lignes.append(f"## {titre}")
            lignes.extend(items if items else ["(rien pour l'instant)"])
            lignes.append("")

        section(
            "Objectifs",
            [f"- {o['nom']} (priorité {o['priorite']}, {o['statut']})" for o in objectifs],
        )
        section(
            "Tâches à faire",
            [
                f"- {t['nom']} (urgence {t['urgence']}"
                + (f", sert : {t['sert']}" if t["sert"] else "")
                + ")"
                for t in taches
            ],
        )

        def _dernier_creneau(creneaux: list) -> str:
            return f", dernier créneau prévu : {sorted(creneaux)[-1]}" if creneaux else ""

        section(
            "Tâches EN COURS (entamées, pas finies — À REPRENDRE EN PRIORITÉ)",
            [
                f"- {t['nom']}"
                + (f" (sert : {t['sert']})" if t["sert"] else "")
                + _dernier_creneau(t["creneaux"])
                for t in en_cours
            ],
        )
        def _seances_txt(seances: list) -> str:
            if not seances:
                return "aucune encore"
            return ", ".join(sorted(seances)[-5:])

        section(
            "Habitudes",
            [
                f"- {h['nom']} ({h['frequence']}) — séances : {_seances_txt(h['seances'])}"
                for h in habitudes
            ],
        )
        section("Personnes", [f"- {p['nom']}" for p in personnes])

        def _ligne_planif(p: dict) -> str:
            ligne = f"- {p['nom'] or '(activité)'} : {p['debut']} → {p['fin']}"
            if p["statut"] == "fait":
                ligne += " — FAIT ✔"
            elif _est_passe(p["debut"], p["fin"]):
                ligne += " — passé, pas encore revu"
            return ligne

        # Occurrences à venir + occurrences passées faites (= cadence réelle des habitudes).
        # Les occurrences « pas faites » ont été supprimées à la révision : pas de fantôme ici.
        section("Agenda (planifié & fait)", [_ligne_planif(p) for p in planifie])

        return "\n".join(lignes)

    # ------------------------------------------------------------------ #
    # ÉCRITURE : applique une action validée. Renvoie un libellé lisible.
    # ------------------------------------------------------------------ #
    def appliquer_action(self, uid: str, a: dict) -> str:
        t = a.get("type")
        nom = a.get("nom") or ""

        # Empêcher de planifier dans le passé (jour ET heure)
        if t in ("planifier", "creer_sortie", "modifier_evenement"):
            debut = a.get("debut")
            if debut and _est_passe(debut, None):
                raise ValueError(
                    f"Impossible de planifier « {nom} » dans le passé ({debut}). "
                    "Choisissez une date/heure future."
                )

        if t == "creer_objectif":
            self._executer(
                "MERGE (m:Utilisateur {uid:$uid}) "
                "MERGE (m)-[:VISE]->(o:Objectif {nom:$nom, uid:$uid}) "
                "SET o.priorite = coalesce($priorite, o.priorite, 'moyenne'), "
                "    o.statut = coalesce(o.statut, 'actif')",
                uid=uid,
                nom=nom,
                priorite=a.get("priorite"),
            )
            return f"Objectif « {nom} » ajouté"

        if t == "creer_tache":
            self._executer(
                "MERGE (m:Utilisateur {uid:$uid}) "
                "MERGE (m)-[:DOIT_FAIRE]->(tt:Tache {nom:$nom, uid:$uid}) "
                "SET tt.urgence = coalesce($urgence, tt.urgence, 'moyenne'), "
                "    tt.duree_min = coalesce($duree_min, tt.duree_min), "
                "    tt.statut = coalesce(tt.statut, 'a_faire') "
                "WITH m, tt "
                "FOREACH (_ IN CASE WHEN $sert IS NULL THEN [] ELSE [1] END | "
                "  MERGE (m)-[:VISE]->(o:Objectif {nom:$sert, uid:$uid}) MERGE (tt)-[:SERT]->(o))",
                uid=uid,
                nom=nom,
                urgence=a.get("urgence"),
                duree_min=a.get("duree_min"),
                sert=a.get("sert_objectif"),
            )
            return f"Tâche « {nom} » ajoutée"

        if t == "creer_habitude":
            self._executer(
                "MERGE (m:Utilisateur {uid:$uid}) "
                "MERGE (m)-[:PRATIQUE]->(h:Habitude {nom:$nom, uid:$uid}) "
                "SET h.frequence = coalesce($frequence, h.frequence) "
                "WITH m, h "
                "FOREACH (_ IN CASE WHEN $sert IS NULL THEN [] ELSE [1] END | "
                "  MERGE (m)-[:VISE]->(o:Objectif {nom:$sert, uid:$uid}) MERGE (h)-[:SERT]->(o))",
                uid=uid,
                nom=nom,
                frequence=a.get("frequence"),
                sert=a.get("sert_objectif"),
            )
            return f"Habitude « {nom} » ajoutée"

        if t == "ajouter_personne":
            self._executer(
                "MERGE (m:Utilisateur {uid:$uid}) "
                "MERGE (m)-[:CONNAIT]->(p:Personne {nom:$nom, uid:$uid})",
                uid=uid,
                nom=nom,
            )
            return f"Personne « {nom} » ajoutée"

        if t == "creer_sortie":
            # MERGE (et non CREATE) sur (nom, debut, uid) : revalider la même suggestion de
            # sortie ne crée pas de doublon (cohérent avec les autres créations).
            self._executer(
                "MERGE (s:Sortie {nom:$nom, debut:$debut, uid:$uid}) "
                "SET s.fin = $fin, s.statut = coalesce(s.statut, 'a_venir') "
                "WITH s "
                "FOREACH (_ IN CASE WHEN $avec IS NULL THEN [] ELSE [1] END | "
                "  MERGE (m:Utilisateur {uid:$uid}) "
                "  MERGE (m)-[:CONNAIT]->(p:Personne {nom:$avec, uid:$uid}) "
                "  MERGE (s)-[:AVEC]->(p)) "
                "FOREACH (_ IN CASE WHEN $sert IS NULL THEN [] ELSE [1] END | "
                "  MERGE (m2:Utilisateur {uid:$uid}) "
                "  MERGE (m2)-[:VISE]->(o:Objectif {nom:$sert, uid:$uid}) MERGE (s)-[:SERT]->(o))",
                uid=uid,
                nom=nom or "Sortie",
                debut=a.get("debut"),
                fin=a.get("fin"),
                avec=a.get("avec"),
                sert=a.get("sert_objectif"),
            )
            avec = f" avec {a['avec']}" if a.get("avec") else ""
            return f"Sortie « {nom or 'Sortie'} »{avec} planifiée"

        if t == "planifier":
            # MERGE (et non CREATE) sur (libelle, debut, uid) : replanifier le même créneau ne
            # crée pas de doublon, même si l'action est validée deux fois.
            maintenant = datetime.now().isoformat(timespec="minutes")
            self._executer(
                "MERGE (c:Creneau {libelle:$nom, debut:$debut, uid:$uid}) "
                # Statut PAR OCCURRENCE : un nouveau créneau est « à venir » tant qu'il n'a pas
                # été révisé (fait / pas fait). C'est ce drapeau qui pilote la carte de révision.
                "SET c.fin = $fin, c.statut = coalesce(c.statut, 'a_venir') "
                "WITH c "
                "OPTIONAL MATCH (x {nom:$nom, uid:$uid}) WHERE x:Tache OR x:Sortie OR x:Habitude "
                "FOREACH (_ IN CASE WHEN x IS NULL THEN [] ELSE [1] END | "
                "  MERGE (x)-[:PLANIFIE_A]->(c)) "
                "WITH c "
                # Replanification : on enlève l'ANCIEN créneau passé non révisé de cette tâche
                # (sinon il reste comme doublon « à revoir »). On épargne les occurrences déjà
                # faites (= historique) et les créneaux encore à venir.
                "OPTIONAL MATCH (tt:Tache {nom:$nom, uid:$uid})-[:PLANIFIE_A]->(vieux:Creneau) "
                "WHERE vieux <> c AND vieux.debut < $now AND coalesce(vieux.statut,'a_venir') <> 'fait' "
                "DETACH DELETE vieux",
                uid=uid,
                nom=nom,
                debut=a.get("debut"),
                fin=a.get("fin"),
                now=maintenant,
            )
            return f"« {nom} » planifié ({a.get('debut')} → {a.get('fin')})"

        if t == "reviser_creneau":
            # RÉVISION d'UNE occurrence (par identifiant), pilotée par le front, sans LLM.
            # Le filtre `uid` garantit qu'on ne révise QUE ses propres éléments (anti-IDOR).
            # `kind` distingue un créneau (tâche/habitude/activité) d'une sortie (rdv).
            cid = a.get("cible_id")
            resultat = a.get("resultat")   # 'fait' | 'commence' | 'pas_fait'

            if a.get("kind") == "sortie":
                # Un rdv : on y est allé (fait) ou pas (on le retire). Pas d'état « commencé ».
                if resultat == "fait":
                    self._executer(
                        "MATCH (s:Sortie) WHERE elementId(s)=$id AND s.uid=$uid SET s.statut='fait'",
                        id=cid, uid=uid,
                    )
                    return "Rendez-vous fait ✔️"
                self._executer(
                    "MATCH (s:Sortie) WHERE elementId(s)=$id AND s.uid=$uid DETACH DELETE s",
                    id=cid, uid=uid,
                )
                return "Rendez-vous non fait — retiré de l'agenda"

            if resultat == "fait":
                # L'occurrence a eu lieu -> verte (historique) ; si tâche unique, elle est finie.
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid SET c.statut='fait'",
                    id=cid, uid=uid,
                )
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                    "MATCH (tt:Tache)-[:PLANIFIE_A]->(c) SET tt.statut='fait'",
                    id=cid, uid=uid,
                )
                return "Occurrence faite ✔️"

            if resultat == "commence":
                # Entamée mais pas finie : la tâche passe « à reprendre » (en_cours) -> colonne
                # latérale ; on retire le créneau passé (Thoth/le côté reprendre la replanifiera).
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                    "MATCH (tt:Tache)-[:PLANIFIE_A]->(c) SET tt.statut='en_cours'",
                    id=cid, uid=uid,
                )
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                    "OPTIONAL MATCH (s:Sortie)-[:PLANIFIE_A]->(c) DETACH DELETE c, s",
                    id=cid, uid=uid,
                )
                return "Occurrence commencée — à reprendre"

            # pas_fait : rien n'a été fait. On retire le créneau ; la tâche RESTE à faire
            # (réserve, sans date) -> Thoth pourra proposer de la reprogrammer.
            self._executer(
                "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                "OPTIONAL MATCH (s:Sortie)-[:PLANIFIE_A]->(c) DETACH DELETE c, s",
                id=cid, uid=uid,
            )
            return "Occurrence non faite — remise en réserve"

        if t == "marquer_fait":
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(tt:Tache {nom:$nom}) SET tt.statut='fait'",
                uid=uid,
                nom=nom,
            )
            # Faite en avance ? On ramène le créneau encore à venir au moment réel
            # (maintenant) ET on le marque fait : le calendrier dit QUAND ça a eu lieu (vert)
            # et le créneau prévu est libéré. Les créneaux déjà passés restent à leur date.
            maintenant = datetime.now().isoformat(timespec="minutes")
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(:Tache {nom:$nom})-[:PLANIFIE_A]->(c:Creneau) "
                "WHERE c.debut > $maintenant "
                "SET c.debut = $maintenant, c.fin = $maintenant, c.statut = 'fait'",
                uid=uid,
                nom=nom,
                maintenant=maintenant,
            )
            return f"Tâche « {nom} » marquée comme faite"

        if t == "noter_progres":
            # « J'ai avancé mais pas fini » : la tâche passe en cours (ambre « à reprendre »,
            # plus de rouge), et Thothbook la reproposera EN PRIORITÉ pour la continuer.
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(tt:Tache {nom:$nom}) SET tt.statut='en_cours'",
                uid=uid,
                nom=nom,
            )
            return f"Tâche « {nom} » en cours (à reprendre)"

        if t == "supprimer_tache":
            # Supprime la tâche ET ses créneaux planifiés (DETACH DELETE ignore c null).
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(t:Tache {nom:$nom}) "
                "OPTIONAL MATCH (t)-[:PLANIFIE_A]->(c:Creneau) "
                "DETACH DELETE t, c",
                uid=uid,
                nom=nom,
            )
            return f"Tâche « {nom} » supprimée"

        if t == "atteindre_objectif":
            # Archive l'objectif et supprime ses tâches NON faites (les faites restent
            # comme historique). Les créneaux de ces tâches partent aussi.
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:VISE]->(o:Objectif {nom:$nom}) SET o.statut='atteint' "
                "WITH o "
                "OPTIONAL MATCH (o)<-[:SERT]-(t:Tache) WHERE coalesce(t.statut,'a_faire') <> 'fait' "
                "OPTIONAL MATCH (t)-[:PLANIFIE_A]->(c:Creneau) "
                "DETACH DELETE t, c",
                uid=uid,
                nom=nom,
            )
            return f"Objectif « {nom} » atteint 🏆"

        if t == "abandonner_objectif":
            # Archive l'objectif et supprime TOUTES ses tâches liées (et leurs créneaux).
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:VISE]->(o:Objectif {nom:$nom}) SET o.statut='abandonne' "
                "WITH o "
                "OPTIONAL MATCH (o)<-[:SERT]-(t:Tache) "
                "OPTIONAL MATCH (t)-[:PLANIFIE_A]->(c:Creneau) "
                "DETACH DELETE t, c",
                uid=uid,
                nom=nom,
            )
            return f"Objectif « {nom} » abandonné"

        if t == "terminer_habitude":
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:PRATIQUE]->(h:Habitude {nom:$nom}) SET h.statut='terminee'",
                uid=uid,
                nom=nom,
            )
            return f"Habitude « {nom} » terminée 🏁"

        if t == "abandonner_habitude":
            self._executer(
                "MATCH (:Utilisateur {uid:$uid})-[:PRATIQUE]->(h:Habitude {nom:$nom}) SET h.statut='abandonnee'",
                uid=uid,
                nom=nom,
            )
            return f"Habitude « {nom} » abandonnée"

        if t == "supprimer_evenement":
            # Suppression directe depuis l'agenda, par identifiant. Le filtre `uid` garantit
            # qu'on ne peut supprimer QUE ses propres événements (correctif IDOR).
            cid = a.get("cible_id")
            if a.get("kind") == "sortie":
                self._executer(
                    "MATCH (s:Sortie) WHERE elementId(s)=$id AND s.uid=$uid DETACH DELETE s",
                    id=cid, uid=uid,
                )
            else:
                # On retire le créneau (la tâche/habitude parente reste, juste « déplanifiée »).
                # Une sortie rattachée à ce créneau, elle, n'a de sens qu'au calendrier : on la
                # supprime aussi pour qu'elle ne réapparaisse pas comme sortie « non planifiée ».
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                    "OPTIONAL MATCH (s:Sortie)-[:PLANIFIE_A]->(c) "
                    "DETACH DELETE c, s",
                    id=cid, uid=uid,
                )
            return "Événement supprimé"

        if t == "modifier_evenement":
            # Déplace/renomme l'événement EXISTANT (par id) au lieu d'en recréer un. Le filtre
            # `uid` garantit qu'on ne modifie QUE ses propres événements (correctif IDOR).
            cid = a.get("cible_id")
            if a.get("kind") == "sortie":
                self._executer(
                    "MATCH (s:Sortie) WHERE elementId(s)=$id AND s.uid=$uid "
                    "SET s.debut=$debut, s.fin=$fin, "
                    "    s.nom=coalesce($titre, s.nom)",
                    id=cid, uid=uid, debut=a.get("debut"), fin=a.get("fin"), titre=(nom or None),
                )
            else:
                self._executer(
                    "MATCH (c:Creneau) WHERE elementId(c)=$id AND c.uid=$uid "
                    "SET c.debut=$debut, c.fin=$fin, "
                    "    c.libelle=coalesce($titre, c.libelle)",
                    id=cid, uid=uid, debut=a.get("debut"), fin=a.get("fin"), titre=(nom or None),
                )
            return "Événement modifié"

        return f"(action inconnue ignorée : {t})"

    # ------------------------------------------------------------------ #
    def lire_etat(self, uid: str) -> dict:
        """Résumé léger pour l'en-tête de l'app : objectifs + tâches en cours."""
        objectifs = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:VISE]->(o:Objectif) "
            "WHERE coalesce(o.statut,'actif') = 'actif' "
            "OPTIONAL MATCH (o)<-[:SERT]-(t:Tache) "
            "RETURN o.nom AS nom, coalesce(o.priorite,'moyenne') AS priorite, "
            "count(t) AS total, "
            "sum(CASE WHEN t.statut = 'fait' THEN 1 ELSE 0 END) AS faites",
            uid=uid,
        )
        maintenant = datetime.now().isoformat(timespec="minutes")
        taches = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(t:Tache) "
            "WHERE coalesce(t.statut,'a_faire') = 'a_faire' "
            "OPTIONAL MATCH (t)-[:SERT]->(o:Objectif) "
            "OPTIONAL MATCH (t)-[:PLANIFIE_A]->(cf:Creneau) WHERE cf.debut >= $now "
            # en_retard = la tâche a un créneau dont l'heure est déjà passée (-> libellé « Fait »).
            "RETURN DISTINCT t.nom AS nom, coalesce(t.urgence,'moyenne') AS urgence, o.nom AS sert, "
            "size([(t)-[:PLANIFIE_A]->(c:Creneau) WHERE c.debut < $now | 1]) > 0 AS en_retard, "
            "min(cf.debut) AS prochaine_seance "
            # Tri par urgence (haute -> moyenne -> basse) puis alphabétique.
            "ORDER BY CASE urgence WHEN 'haute' THEN 0 WHEN 'moyenne' THEN 1 ELSE 2 END, toLower(nom)",
            uid=uid,
            now=maintenant,
        )
        en_cours = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:DOIT_FAIRE]->(t:Tache) WHERE t.statut = 'en_cours' "
            "OPTIONAL MATCH (t)-[:SERT]->(o:Objectif) "
            "OPTIONAL MATCH (t)-[:PLANIFIE_A]->(cf:Creneau) WHERE cf.debut >= $now "
            "RETURN DISTINCT t.nom AS nom, coalesce(t.urgence,'moyenne') AS urgence, o.nom AS sert, "
            "min(cf.debut) AS prochaine_seance",
            uid=uid,
            now=maintenant,
        )
        habitudes = self._executer(
            "MATCH (:Utilisateur {uid:$uid})-[:PRATIQUE]->(h:Habitude) "
            "WHERE coalesce(h.statut,'active') = 'active' "
            "RETURN h.nom AS nom, coalesce(h.frequence,'?') AS frequence, "
            "[(h)-[:PLANIFIE_A]->(c:Creneau) WHERE c.debut IS NOT NULL | c.debut] AS seances",
            uid=uid,
        )
        return {
            "objectifs": objectifs,
            "taches": taches,
            "en_cours": en_cours,
            "habitudes": habitudes,
            "stats": self.stats(uid),
        }

    # ------------------------------------------------------------------ #
    def lire_agenda(self, uid: str) -> list[dict]:
        """Tout ce qui est planifié (créneaux + sorties), pour la vue calendrier."""
        creneaux = self._executer(
            "MATCH (c:Creneau {uid:$uid}) WHERE c.debut IS NOT NULL "
            "OPTIONAL MATCH (x)-[:PLANIFIE_A]->(c) "
            "RETURN elementId(c) AS id, 'creneau' AS kind, "
            "coalesce(c.libelle, x.nom, 'Activité') AS titre, "
            # Le statut vit désormais sur l'OCCURRENCE (le créneau), pas sur la tâche parente :
            # une habitude lue lundi mais pas mardi a deux créneaux de statuts différents.
            "c.debut AS debut, c.fin AS fin, labels(x) AS labels, coalesce(c.statut,'a_venir') AS statut",
            uid=uid,
        )
        sorties = self._executer(
            # On exclut les sorties déjà rattachées à un créneau : elles remontent déjà via
            # la requête `creneaux` ci-dessus (sinon elles apparaîtraient deux fois).
            "MATCH (s:Sortie {uid:$uid}) WHERE s.debut IS NOT NULL AND NOT (s)-[:PLANIFIE_A]->(:Creneau) "
            "RETURN elementId(s) AS id, 'sortie' AS kind, "
            "s.nom AS titre, s.debut AS debut, s.fin AS fin, ['Sortie'] AS labels, "
            "coalesce(s.statut,'a_venir') AS statut",
            uid=uid,
        )
        return [
            {
                "id": r["id"],
                "kind": r["kind"],
                "titre": r["titre"],
                "debut": r["debut"],
                "fin": r["fin"],
                "type": (r["labels"] or ["activite"])[0].lower(),
                "statut": _statut_agenda(r["debut"], r["fin"], r["statut"], r["kind"]),
            }
            for r in creneaux + sorties
        ]

    # ------------------------------------------------------------------ #
    def stats(self, uid: str) -> dict:
        rows = self._executer(
            "MATCH (n {uid:$uid}) WHERE NOT n:Utilisateur "
            "RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label",
            uid=uid,
        )
        return {r["label"]: r["n"] for r in rows if r["label"]}
