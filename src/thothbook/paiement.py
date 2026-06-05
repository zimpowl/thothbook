"""Paiements Stripe et configuration des packs de crédits."""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

try:  # Import optionnel pour garder le projet importable sans Stripe en dev hors paiement.
    import stripe
except ImportError:  # pragma: no cover - couvert implicitement par le fallback runtime.
    stripe = None


class PaiementErreur(RuntimeError):
    """Erreur métier de paiement."""


class PaiementConfigurationErreur(PaiementErreur):
    """Configuration Stripe absente ou invalide."""


class PackInconnuErreur(PaiementErreur):
    """Pack demandé inconnu."""


def _lire(obj: Any, cle: str, default=None):
    """Lit une clé sur dict, StripeObject ou objet arbitraire."""
    if obj is None:
        return default
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(cle, default)
        except TypeError:
            pass
    if hasattr(obj, cle):
        return getattr(obj, cle)
    try:
        return obj[cle]
    except Exception:
        return default


def _centimes(montant_eur: Decimal) -> int:
    return int((montant_eur * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def lister_packs(cfg: dict) -> list[dict[str, Any]]:
    """Normalise les packs configurés pour le front et Stripe."""
    packs = []
    for rang, brut in enumerate(cfg.get("credits", {}).get("packs", []), start=1):
        credits = int(brut.get("credits") or 0)
        bonus = int(brut.get("bonus_credits") or 0)
        total = credits + bonus
        prix_eur = Decimal(str(brut.get("prix_eur", 0) or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not brut.get("id") or total <= 0 or prix_eur <= 0:
            continue
        packs.append(
            {
                "id": str(brut["id"]),
                "label": str(brut.get("label") or f"Pack {rang}"),
                "description": str(brut.get("description") or "Recharge de crédits"),
                "prix_eur": float(prix_eur),
                "prix_centimes": _centimes(prix_eur),
                "credits": credits,
                "bonus_credits": bonus,
                "total_credits": total,
                "badge": str(brut.get("badge") or ""),
                "ordre": int(brut.get("ordre") or rang),
            }
        )
    return sorted(packs, key=lambda p: (p["ordre"], p["prix_centimes"]))


def pack_par_id(cfg: dict, pack_id: str) -> dict[str, Any]:
    for pack in lister_packs(cfg):
        if pack["id"] == pack_id:
            return pack
    raise PackInconnuErreur(f"Pack inconnu : {pack_id}")


def stripe_active() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY")) and stripe is not None


def _stripe_client():
    if stripe is None:
        raise PaiementConfigurationErreur("La dépendance Stripe n'est pas installée.")
    cle = os.environ.get("STRIPE_SECRET_KEY")
    if not cle:
        raise PaiementConfigurationErreur("STRIPE_SECRET_KEY manquante.")
    stripe.api_key = cle
    return stripe


def offres_paiement(cfg: dict) -> dict[str, Any]:
    devise = str(cfg.get("paiements", {}).get("devise", "eur") or "eur").lower()
    return {"actif": stripe_active(), "devise": devise, "packs": lister_packs(cfg)}


def creer_session_checkout(cfg: dict, base_url: str, uid: str, email: str | None, pack_id: str) -> dict[str, str]:
    client = _stripe_client()
    pack = pack_par_id(cfg, pack_id)
    origine = base_url.rstrip("/")
    devise = str(cfg.get("paiements", {}).get("devise", "eur") or "eur").lower()

    session = client.checkout.Session.create(
        mode="payment",
        locale="fr",
        success_url=f"{origine}/?checkout=success",
        cancel_url=f"{origine}/?checkout=cancel",
        customer_email=email or None,
        allow_promotion_codes=False,
        metadata={
            "uid": uid,
            "pack_id": pack["id"],
            "credits": str(pack["credits"]),
            "bonus_credits": str(pack["bonus_credits"]),
            "credits_total": str(pack["total_credits"]),
        },
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": devise,
                    "unit_amount": pack["prix_centimes"],
                    "product_data": {
                        "name": f"Thothbook — {pack['label']}",
                        "description": (
                            f"{pack['total_credits']} crédits"
                            + (f" dont {pack['bonus_credits']} offerts" if pack["bonus_credits"] else "")
                        ),
                    },
                },
            }
        ],
    )
    return {"id": session.id, "url": session.url}


def construire_evenement_webhook(payload: bytes, signature: str | None):
    client = _stripe_client()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise PaiementConfigurationErreur("STRIPE_WEBHOOK_SECRET manquante.")
    if not signature:
        raise PaiementErreur("Signature Stripe absente.")
    return client.Webhook.construct_event(payload, signature, secret)


def traiter_evenement_stripe(cfg: dict, graphe, event: Any, credits_par_euro: int) -> dict[str, Any]:
    """Applique le webhook Stripe utile et ignore le reste."""
    event_type = _lire(event, "type")
    if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return {"ignore": True, "reason": "event_non_pris_en_charge", "event_type": event_type}

    session = _lire(_lire(event, "data", {}), "object", {})
    payment_status = _lire(session, "payment_status")

    # Pour checkout.session.completed : on n'agit que si le paiement est final.
    # "unpaid" = paiement asynchrone en attente → on attend checkout.session.async_payment_succeeded.
    # Pour async_payment_succeeded : payment_status est déjà "paid", pas de filtre nécessaire.
    if event_type == "checkout.session.completed" and payment_status not in {"paid", "no_payment_required"}:
        return {
            "ignore": True,
            "reason": "paiement_pas_encore_final_attente_async_payment_succeeded",
            "event_type": event_type,
            "payment_status": payment_status,
        }

    metadata = _lire(session, "metadata", {}) or {}
    uid = _lire(metadata, "uid")
    credits_total = int(_lire(metadata, "credits_total") or 0)
    if not uid or credits_total <= 0:
        raise PaiementErreur("Webhook Stripe sans uid ou sans crédits.")

    email = (_lire(_lire(session, "customer_details", {}) or {}, "email") or _lire(session, "customer_email"))
    graphe.assurer_utilisateur(uid, email=email, offert=0, credits_par_euro=credits_par_euro)
    recharge = graphe.crediter_recharge_externe(
        uid=uid,
        montant=credits_total,
        provider="stripe",
        reference=str(_lire(session, "id") or ""),
        source=f"stripe:{_lire(metadata, 'pack_id', 'pack')}",
        brut_centimes=int(_lire(session, "amount_total") or 0),
        meta={
            "event_type": event_type,
            "payment_status": payment_status,
            "pack_id": _lire(metadata, "pack_id"),
            "credits": _lire(metadata, "credits"),
            "bonus_credits": _lire(metadata, "bonus_credits"),
            "credits_total": _lire(metadata, "credits_total"),
        },
    )
    return {"ignore": False, "event_type": event_type, "payment_status": payment_status, **recharge}

