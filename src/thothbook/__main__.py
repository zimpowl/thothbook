"""Point d'entrée : `python -m thothbook` (chat) ou `python -m thothbook --seed`."""

import argparse

from .cli import console, lancer_chat
from .config import ROOT, charger_config
from .graphe import Graphe


def _charger_seed() -> None:
    """Charge data/seed.cypher dans la base (instructions séparées par ';')."""
    cfg = charger_config()
    graphe = Graphe(cfg["neo4j"]["uri"], cfg["neo4j"]["user"], cfg["neo4j"]["password"])
    texte = (ROOT / "data" / "seed.cypher").read_text(encoding="utf-8")
    instructions = [s.strip() for s in texte.split(";") if s.strip() and not s.strip().startswith("//")]
    for instr in instructions:
        graphe._executer(instr)
    console.print(f"[green]✓[/] {len(instructions)} instructions chargées. Graphe : {graphe.stats()}")
    graphe.fermer()


def main() -> None:
    parser = argparse.ArgumentParser(prog="thothbook", description="Thothbook — organisation personnelle.")
    parser.add_argument("--seed", action="store_true", help="Charge un graphe d'exemple puis quitte.")
    parser.add_argument("--web", action="store_true", help="Lance l'app web (dans le navigateur).")
    args = parser.parse_args()

    if args.seed:
        _charger_seed()
    elif args.web:
        import uvicorn

        console.print("[bold blue]Thothbook[/] → ouvre http://localhost:8000 dans ton navigateur")
        uvicorn.run("thothbook.api:app", host="127.0.0.1", port=8000, reload=False)
    else:
        lancer_chat()


if __name__ == "__main__":
    main()
