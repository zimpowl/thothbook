"""Chargement de la configuration (config.yaml) et des secrets (.env)."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Racine du projet : .../thothbook  (ce fichier est dans src/thothbook/)
ROOT = Path(__file__).resolve().parents[2]


def charger_config() -> dict:
    """Lit config.yaml, charge .env, et injecte le mot de passe Neo4j depuis l'environnement."""
    load_dotenv(ROOT / ".env")

    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Le mot de passe Neo4j ne vit que dans .env, jamais dans config.yaml.
    cfg["neo4j"]["password"] = os.environ.get("NEO4J_PASSWORD", "")

    if not cfg["neo4j"]["password"]:
        raise RuntimeError(
            "NEO4J_PASSWORD manquant. Copie .env.example en .env et renseigne tes clés."
        )

    return cfg
