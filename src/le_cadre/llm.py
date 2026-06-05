"""Construction du modèle LLM, paramétrable (OpenAI / Gemini) via config.yaml.

On utilise `init_chat_model` de LangChain qui gère les deux fournisseurs avec
la même interface, et `with_structured_output` pour forcer une réponse au format
`Reponse` (validée par Pydantic). Changer de fournisseur = changer config.yaml.

`include_raw=True` : le modèle renvoie un dict {"raw", "parsed", "parsing_error"}
au lieu du seul objet parsé. On a besoin du `raw` pour lire `usage_metadata`
(nombre de tokens) -> facturation des crédits (voir credits.py).
"""

from langchain.chat_models import init_chat_model

from .schemas import Reponse


def construire_modele(cfg: dict):
    llm = cfg["llm"]
    modele = init_chat_model(
        llm["model"],
        model_provider=llm["provider"],
        temperature=llm.get("temperature", 0),
    )
    # Le modèle renverra toujours un objet Reponse, pas du texte brut. include_raw=True
    # nous donne en plus l'AIMessage brut pour compter les tokens consommés.
    return modele.with_structured_output(Reponse, include_raw=True)
