"""Interface conversationnelle en terminal pour Thothbook.

Boucle : tu écris -> Thothbook propose des suggestions -> tu valides (elles
s'écrivent dans le graphe) ou tu clarifies (il re-suggère).
"""

import re
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.panel import Panel

from .conseil import generer_reponse
from .config import charger_config
from .graphe import Graphe
from .llm import construire_modele
from .schemas import Suggestion

console = Console()

# La CLI est un outil de dev local mono-utilisateur : pas de Firebase, on travaille
# sur un utilisateur fixe « cli-dev » (et sans garde crédits).
UID_DEV = "cli-dev"


def _afficher_reponse(message: str, suggestions: list[Suggestion]) -> None:
    console.print(Panel(message, title="🟦 Thothbook", border_style="blue"))
    for i, s in enumerate(suggestions, start=1):
        quand = f"  •  [italic]{s.quand}[/]" if s.quand else ""
        console.print(f"[bold cyan]{i}.[/] [bold]{s.titre}[/]{quand}")
        console.print(f"   [dim]Pourquoi :[/] {s.pourquoi}")
        if s.actions:
            apercu = ", ".join(a.type for a in s.actions)
            console.print(f"   [dim]Écrira dans le graphe :[/] {apercu}")
    if suggestions:
        console.print(
            "\n[dim]→ « ok » pour tout valider, « 1,3 » pour choisir, "
            "ou écris une clarification.[/]"
        )


def _appliquer(graphe: Graphe, suggestions: list[Suggestion]) -> None:
    console.print("[bold green]Écriture dans le graphe…[/]")
    for s in suggestions:
        for a in s.actions:
            msg = graphe.appliquer_action(UID_DEV, a.model_dump())
            console.print(f"  [green]✓[/] {msg}")
    stats = graphe.stats(UID_DEV)
    resume = "  ".join(f"{k}:{v}" for k, v in stats.items()) or "(vide)"
    console.print(f"[dim]Graphe actuel → {resume}[/]")
    console.print(
        "[dim]Vois-le se remplir dans Neo4j Browser (http://localhost:7474) : "
        "[/][italic]MATCH (n) RETURN n[/]\n"
    )


def lancer_chat() -> None:
    cfg = charger_config()
    graphe = Graphe(cfg["neo4j"]["uri"], cfg["neo4j"]["user"], cfg["neo4j"]["password"])
    graphe.assurer_utilisateur(UID_DEV, email="cli@local")
    modele = construire_modele(cfg)

    console.print(
        Panel(
            "Bienvenue dans Thothbook.\n\n"
            "Je ne suis pas là pour te contraindre, je suis là pour te guider.\n"
            "Raconte-moi ta journée, tes objectifs, ou demande-moi quoi faire.\n\n"
            "[dim]Commandes : « voir » (état du graphe) · « q » (quitter)[/]",
            title="Thothbook",
            border_style="blue",
        )
    )

    historique: list = []
    en_attente: list[Suggestion] = []

    try:
        while True:
            user = console.input("\n[bold]👤 toi[/] › ").strip()
            bas = user.lower()

            if bas in {"q", "quit", "exit"}:
                console.print("Reste sur ta trajectoire. 🎯")
                break
            if not user:
                continue
            if bas == "voir":
                stats = graphe.stats(UID_DEV)
                console.print(stats or "(graphe vide)")
                continue

            # Validation des suggestions en attente : "ok" / "oui" / "1,3"
            est_validation = bas in {"ok", "oui", "valide", "valider"} or re.fullmatch(
                r"[\d]+(\s*,\s*[\d]+)*", bas
            )
            if en_attente and est_validation:
                if bas in {"ok", "oui", "valide", "valider"}:
                    choisies = en_attente
                else:
                    idx = [int(n) for n in re.split(r"\s*,\s*", bas)]
                    choisies = [en_attente[i - 1] for i in idx if 1 <= i <= len(en_attente)]
                _appliquer(graphe, choisies)
                historique.append(HumanMessage(content=f"[J'ai validé : {', '.join(s.titre for s in choisies)}]"))
                en_attente = []
                continue

            # Sinon : nouveau message / clarification pour le LLM.
            historique.append(HumanMessage(content=user))
            with console.status("[blue]Thothbook réfléchit…[/]"):
                contexte = graphe.lire_contexte(UID_DEV)
                date_str = datetime.now().strftime("%A %d %B %Y")
                reponse, _usage = generer_reponse(modele, contexte, historique, date_str)  # CLI dev : pas de facturation
            historique.append(AIMessage(content=reponse.message))
            en_attente = reponse.suggestions
            _afficher_reponse(reponse.message, en_attente)
    finally:
        graphe.fermer()
