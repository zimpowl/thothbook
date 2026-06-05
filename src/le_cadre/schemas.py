"""Structure des réponses du Cadre.

Le LLM ne renvoie pas du texte libre : il renvoie un objet `Reponse` validé.
Chaque suggestion contient des `Action` qui, si tu les valides, sont écrites
dans le graphe Neo4j. C'est ce qui fait que la base se remplit quand tu prompt.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# Les seules opérations que Thoth a le droit d'appliquer au graphe.
TypeAction = Literal[
    "creer_objectif",
    "creer_tache",
    "creer_habitude",
    "ajouter_personne",
    "creer_sortie",
    "planifier",
    "marquer_fait",
    "noter_progres",
    "supprimer_tache",
    "atteindre_objectif",
    "abandonner_objectif",
    "terminer_habitude",
    "abandonner_habitude",
    "reviser_creneau",
    "supprimer_evenement",
    "modifier_evenement",
]


class Action(BaseModel):
    """Une opération atomique à appliquer au graphe si l'utilisateur valide."""

    type: TypeAction = Field(description="Le type d'opération à appliquer au graphe.")
    nom: str = Field(
        default="",
        description="Nom de l'élément concerné (objectif, tâche, sortie, habitude, personne).",
    )
    sert_objectif: Optional[str] = Field(
        default=None, description="Nom de l'objectif que cet élément sert, si pertinent."
    )
    avec: Optional[str] = Field(default=None, description="Personne concernée pour une sortie.")
    debut: Optional[str] = Field(
        default=None, description="Date/heure de début ISO 8601, ex : 2026-06-05T18:00"
    )
    fin: Optional[str] = Field(default=None, description="Date/heure de fin ISO 8601.")
    duree_min: Optional[int] = Field(default=None, description="Durée en minutes.")
    priorite: Optional[str] = Field(default=None, description="haute / moyenne / basse")
    urgence: Optional[str] = Field(default=None, description="haute / moyenne / basse")
    frequence: Optional[str] = Field(
        default=None, description="Pour une habitude, ex : quotidienne, hebdomadaire."
    )
    cible_id: Optional[str] = Field(
        default=None,
        description="elementId Neo4j de l'élément d'agenda visé "
        "(reviser_creneau / supprimer_evenement / modifier_evenement).",
    )
    kind: Optional[str] = Field(
        default=None, description="Type du nœud d'agenda visé : 'creneau' ou 'sortie'."
    )
    resultat: Optional[str] = Field(
        default=None, description="Pour reviser_creneau : 'fait' / 'commence' / 'pas_fait'."
    )


class Suggestion(BaseModel):
    """Une suggestion concrète et actionnable du Cadre."""

    titre: str = Field(description="Quoi faire, en une phrase courte.")
    quand: Optional[str] = Field(default=None, description="Quand, en langage naturel.")
    pourquoi: str = Field(description="En quoi ça sert tes objectifs.")
    actions: List[Action] = Field(
        default_factory=list,
        description="Opérations à écrire dans le graphe si l'utilisateur valide cette suggestion.",
    )


class Reponse(BaseModel):
    """Ce que le Cadre renvoie à chaque tour."""

    message: str = Field(description="Message conversationnel du Cadre adressé à l'utilisateur.")
    suggestions: List[Suggestion] = Field(default_factory=list)
