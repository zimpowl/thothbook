"""Tarification & facturation des appels LLM.

Le provider facture en euros, mais l'application débite des CRÉDITS entiers.
Le calcul est donc : coût réel (euros) × marge × crédits_par_euro, arrondi au-dessus.
Un minimum par appel peut être imposé pour garder une perception « premium ».
"""

from math import ceil


def cout_reel(cfg: dict, modele: str, tokens_in: int, tokens_out: int) -> float:
    """Coût provider d'un appel, en euros, d'après la grille de config.yaml."""
    tarifs = cfg.get("tarifs", {})
    modeles = tarifs.get("modeles", {})
    grille = modeles.get(modele) or tarifs.get("defaut") or {}
    prix_in = grille.get("input_par_million", 0.0)
    prix_out = grille.get("output_par_million", 0.0)
    return tokens_in / 1_000_000 * prix_in + tokens_out / 1_000_000 * prix_out


def credits_a_facturer(cfg: dict, cout_eur: float, usage_presente: bool = True) -> int:
    """Convertit un coût réel (euros) en crédits entiers facturés.

    - `credits.par_euro` définit combien de crédits valent 1 € payé.
    - `tarifs.marge` permet d'appliquer une très forte marge commerciale.
    - `credits.debit_minimum` impose un plancher par appel LLM.
    """
    if not usage_presente:
        return 0

    credits_cfg = cfg.get("credits", {})
    credits_par_euro = int(credits_cfg.get("par_euro", 100) or 100)
    minimum = int(credits_cfg.get("debit_minimum", 1) or 1)
    marge = float(cfg.get("tarifs", {}).get("marge", 1.0) or 1.0)

    brut = ceil(cout_eur * marge * credits_par_euro)
    return max(minimum, int(brut))


def facturer_appel(cfg: dict, graphe, uid: str, modele: str, usage: dict | None) -> dict:
    """Calcule le coût réel, débite des crédits entiers et journalise.

    `usage` est le dict usage_metadata de LangChain ({input_tokens, output_tokens, ...}).
    S'il est absent (pas de métadonnées), on ne facture rien plutôt que de deviner.
    Renvoie {tokens_in, tokens_out, cout_reel_eur, credits_factures, solde}.
    """
    if not usage:
        return {
            "tokens_in": 0,
            "tokens_out": 0,
            "cout_reel_eur": 0.0,
            "credits_factures": 0,
            "solde": graphe.solde(uid),
        }

    tokens_in = int(usage.get("input_tokens", 0) or 0)
    tokens_out = int(usage.get("output_tokens", 0) or 0)
    cr = cout_reel(cfg, modele, tokens_in, tokens_out)
    credits = credits_a_facturer(cfg, cr, usage_presente=(tokens_in > 0 or tokens_out > 0))

    solde = graphe.debiter(uid, credits)
    graphe.journaliser_usage(uid, modele, tokens_in, tokens_out, cr, credits)
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cout_reel_eur": cr,
        "credits_factures": credits,
        "solde": solde,
    }
