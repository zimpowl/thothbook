"""Authentification Firebase côté backend.

Le frontend obtient un jeton d'identité Firebase (ID token) et l'envoie dans
l'en-tête `Authorization: Bearer <token>`. Ici on vérifie ce jeton avec le SDK
Admin et on en déduit l'UID de l'utilisateur. Toutes les routes data dépendent
de `utilisateur_courant` : sans jeton valide, pas d'accès.

Initialisation des identifiants Firebase :
  - En local : variable d'env FIREBASE_CREDENTIALS = chemin vers le JSON de compte
    de service (téléchargé depuis la console Firebase).
  - Sur Cloud Run : rien à faire, les Application Default Credentials (ADC) sont
    fournies automatiquement par l'environnement Google -> initialize_app() sans clé.
"""

import os

import firebase_admin
from fastapi import Header, HTTPException, status
from firebase_admin import auth, credentials

_initialise = False


def _init_firebase() -> None:
    """Initialise l'app Firebase Admin une seule fois (idempotent)."""
    global _initialise
    if _initialise or firebase_admin._apps:
        _initialise = True
        return
    chemin = os.environ.get("FIREBASE_CREDENTIALS")
    if chemin:
        firebase_admin.initialize_app(credentials.Certificate(chemin))
    else:
        # Cloud Run / GCP : Application Default Credentials.
        firebase_admin.initialize_app()
    _initialise = True


def utilisateur_courant(authorization: str = Header(default="")) -> dict:
    """Dépendance FastAPI : vérifie le Bearer token Firebase et renvoie {uid, email}.

    Lève 401 si l'en-tête est absent/malformé ou si le jeton est invalide/expiré.
    """
    _init_firebase()
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len("Bearer "):].strip()
    try:
        decode = auth.verify_id_token(token)
    except Exception:  # jeton invalide, expiré, mauvaise signature, etc.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"uid": decode["uid"], "email": decode.get("email")}
