"""
Dealyze — Facturation Lemon Squeezy
Routes : /billing/*

Deux modes :
  - SIMULATION_MODE=true  → pas besoin de compte, le paiement est simulé (hackathon)
  - SIMULATION_MODE=false → appels réels à l'API Lemon Squeezy
"""
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from config.settings import settings
from models.database import get_db
from models.user import User, get_user_by_id, update_user_subscription

logger = logging.getLogger(__name__)
router = APIRouter()

LS_API = "https://api.lemonsqueezy.com/v1"


# --------------------------------------------------------------------------- #
# Définition des plans                                                         #
# --------------------------------------------------------------------------- #

PLANS = {
    "starter": {
        "nom": "Starter",
        "prix": 47,
        "devise": "USD",
        "variant_id": settings.ls_variant_starter,
        "description": "Pour les PME qui démarrent",
        "fonctionnalites": [
            "17 devis / mois (Deal Draft)",
            "17 relances / mois (Smart Chase)",
            "5 analyses pitch / mois (Pitch Radar)",
            "3 due diligences / mois (Deep Due)",
            "Support par email",
        ],
    },
    "growth": {
        "nom": "Growth",
        "prix": 147,
        "devise": "USD",
        "variant_id": settings.ls_variant_growth,
        "description": "Pour les équipes en croissance",
        "fonctionnalites": [
            "Agents illimités",
            "Export PDF des rapports",
            "Historique complet",
            "Support prioritaire",
            "API access",
        ],
    },
    "enterprise": {
        "nom": "Enterprise",
        "prix": 477,
        "devise": "USD",
        "variant_id": settings.ls_variant_enterprise,
        "description": "Pour les fonds et cabinets",
        "fonctionnalites": [
            "Tout Growth inclus",
            "Multi-utilisateurs (5 sièges)",
            "White-label possible",
            "SLA garanti",
            "Onboarding dédié",
        ],
    },
}

# Correspondance variant_id → nom du plan (utilisé dans le webhook)
VARIANT_TO_PLAN: dict[str, str] = {
    v["variant_id"]: k for k, v in PLANS.items() if v["variant_id"]
}


# --------------------------------------------------------------------------- #
# Helpers Lemon Squeezy                                                        #
# --------------------------------------------------------------------------- #

def _ls_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


def _verify_ls_signature(payload: bytes, signature: str) -> bool:
    """Vérifie la signature HMAC-SHA256 du webhook Lemon Squeezy."""
    expected = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# --------------------------------------------------------------------------- #
# GET /billing/plans  — public                                                 #
# --------------------------------------------------------------------------- #

@router.get("/plans")
def list_plans():
    """Retourne les 3 plans disponibles avec leurs fonctionnalités et prix."""
    return [
        {
            "plan_id": key,
            "nom": p["nom"],
            "prix_mensuel": p["prix"],
            "devise": p["devise"],
            "description": p["description"],
            "fonctionnalites": p["fonctionnalites"],
        }
        for key, p in PLANS.items()
    ]


# --------------------------------------------------------------------------- #
# GET /billing/mode  — public (utile pour le jury)                             #
# --------------------------------------------------------------------------- #

@router.get("/mode")
def billing_mode():
    """Indique si le paiement est en mode simulation ou réel."""
    return {
        "mode": "simulation" if settings.simulation_mode else "production",
        "provider": "Lemon Squeezy" if not settings.simulation_mode else "N/A",
        "configured": bool(settings.lemonsqueezy_api_key) or settings.simulation_mode,
    }


# --------------------------------------------------------------------------- #
# POST /billing/checkout  — protégé                                            #
# --------------------------------------------------------------------------- #

class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "growth" | "enterprise"


@router.post("/checkout")
def create_checkout(
    req: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Crée une session de paiement.
    - Mode simulation : retourne une URL simulée et active le plan immédiatement.
    - Mode production : crée un checkout Lemon Squeezy réel.
    """
    plan = PLANS.get(req.plan)
    if not plan:
        raise HTTPException(422, f"Plan inconnu : {req.plan}. Choisir starter, growth ou enterprise.")

    # ------------------------------------------------------------------ #
    # MODE SIMULATION                                                       #
    # ------------------------------------------------------------------ #
    if settings.simulation_mode:
        sim_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"

        # On active le plan directement en DB (simule le webhook)
        update_user_subscription(
            db, current_user,
            plan=req.plan,
            stripe_customer_id=f"sim_cust_{current_user.id[:8]}",
            stripe_subscription_id=sim_id,
            subscription_status="active",
        )

        logger.info("[Billing-SIM] Paiement simulé | user=%s | plan=%s | id=%s",
                    current_user.email, req.plan, sim_id)

        return {
            "mode": "simulation",
            "message": f"✅ Plan {plan['nom']} activé en mode simulation (hackathon)",
            "checkout_url": f"/dashboard?payment=simulated&plan={req.plan}",
            "simulation_id": sim_id,
            "plan_active": req.plan,
            "montant": f"{plan['prix']} {plan['devise']}/mois",
        }

    # ------------------------------------------------------------------ #
    # MODE PRODUCTION — Lemon Squeezy                                       #
    # ------------------------------------------------------------------ #
    if not settings.lemonsqueezy_api_key:
        raise HTTPException(503, "Paiement non configuré. Ajouter LEMONSQUEEZY_API_KEY dans .env ou activer SIMULATION_MODE=true.")

    if not plan["variant_id"]:
        raise HTTPException(503, f"Variant ID Lemon Squeezy manquant pour le plan {req.plan}.")

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": current_user.email,
                    "name": current_user.full_name,
                    "custom": {
                        "user_id": current_user.id,
                        "plan": req.plan,
                    },
                },
                "product_options": {
                    "redirect_url": f"{settings.app_url}/dashboard?payment=success&plan={req.plan}",
                },
            },
            "relationships": {
                "store": {
                    "data": {"type": "stores", "id": settings.lemonsqueezy_store_id}
                },
                "variant": {
                    "data": {"type": "variants", "id": plan["variant_id"]}
                },
            },
        }
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{LS_API}/checkouts", headers=_ls_headers(), json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("[LemonSqueezy] Checkout error %s: %s", e.response.status_code, e.response.text)
        raise HTTPException(502, f"Erreur Lemon Squeezy : {e.response.text}")
    except httpx.RequestError as e:
        logger.error("[LemonSqueezy] Network error: %s", e)
        raise HTTPException(502, "Impossible de joindre Lemon Squeezy.")

    data = resp.json()
    checkout_url = data["data"]["attributes"]["url"]
    logger.info("[Billing] Checkout LS créé | user=%s | plan=%s", current_user.email, req.plan)

    return {"checkout_url": checkout_url, "mode": "production"}


# --------------------------------------------------------------------------- #
# POST /billing/simulate-upgrade  — protégé (demo jury)                       #
# --------------------------------------------------------------------------- #

class SimulateUpgradeRequest(BaseModel):
    plan: str
    status: str = "active"  # "active" | "trialing" | "canceled"


@router.post("/simulate-upgrade")
def simulate_upgrade(
    req: SimulateUpgradeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Endpoint de démonstration — permet au jury de changer de plan instantanément
    sans passer par le paiement. Toujours disponible, même en mode production.
    """
    if req.plan not in PLANS and req.plan != "free_trial":
        raise HTTPException(422, f"Plan inconnu : {req.plan}")

    sim_id = f"DEMO-{uuid.uuid4().hex[:8].upper()}"
    update_user_subscription(
        db, current_user,
        plan=req.plan,
        stripe_customer_id=f"demo_cust_{current_user.id[:8]}",
        stripe_subscription_id=sim_id,
        subscription_status=req.status,
    )

    logger.info("[Billing-DEMO] Plan changé | user=%s | plan=%s | statut=%s",
                current_user.email, req.plan, req.status)

    return {
        "message": f"Plan changé en {req.plan} (mode démo)",
        "plan": req.plan,
        "subscription_status": req.status,
        "demo_id": sim_id,
    }


# --------------------------------------------------------------------------- #
# GET /billing/subscription  — protégé                                         #
# --------------------------------------------------------------------------- #

@router.get("/subscription")
def get_subscription(current_user: User = Depends(get_current_user)):
    """Retourne l'état de l'abonnement de l'utilisateur connecté."""
    plan_info = PLANS.get(current_user.plan)
    return {
        "plan": current_user.plan,
        "plan_nom": plan_info["nom"] if plan_info else "Essai gratuit",
        "subscription_status": current_user.subscription_status,
        "ls_customer_id": current_user.stripe_customer_id,
        "ls_subscription_id": current_user.stripe_subscription_id,
    }


# --------------------------------------------------------------------------- #
# POST /billing/webhook  — appelé par Lemon Squeezy                            #
# --------------------------------------------------------------------------- #

@router.post("/webhook")
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: str = Header(None, alias="x-signature"),
    db: Session = Depends(get_db),
):
    """
    Webhook Lemon Squeezy.
    Configurer dans le dashboard LS : Settings → Webhooks → Add webhook
    URL : https://votre-domaine/billing/webhook
    Événements : subscription_created, subscription_updated, subscription_cancelled
    """
    payload = await request.body()

    # Vérification signature
    if settings.lemonsqueezy_webhook_secret and x_signature:
        if not _verify_ls_signature(payload, x_signature):
            logger.warning("[LemonSqueezy] Webhook : signature invalide")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature invalide.")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "Payload JSON invalide.")

    event_name = event.get("meta", {}).get("event_name", "")
    custom_data = event.get("meta", {}).get("custom_data", {})
    user_id = custom_data.get("user_id")
    plan = custom_data.get("plan", "starter")

    logger.info("[LemonSqueezy] Webhook reçu : %s | user_id=%s", event_name, user_id)

    if not user_id:
        return {"received": True}

    user = get_user_by_id(db, user_id)
    if not user:
        logger.warning("[LemonSqueezy] Webhook : user_id %s introuvable", user_id)
        return {"received": True}

    attrs = event.get("data", {}).get("attributes", {})
    sub_status = attrs.get("status", "active")
    ls_customer_id = str(attrs.get("customer_id", ""))
    ls_sub_id = str(event.get("data", {}).get("id", ""))

    # Variant → plan
    first_item = attrs.get("first_subscription_item", {})
    variant_id = str(first_item.get("variant_id", ""))
    if variant_id and variant_id in VARIANT_TO_PLAN:
        plan = VARIANT_TO_PLAN[variant_id]

    if event_name in ("subscription_created", "subscription_updated", "subscription_payment_success"):
        update_user_subscription(
            db, user,
            plan=plan,
            stripe_customer_id=ls_customer_id,
            stripe_subscription_id=ls_sub_id,
            subscription_status=sub_status,
        )
        logger.info("[Billing] Abonnement mis à jour | user=%s | plan=%s | statut=%s",
                    user.email, plan, sub_status)

    elif event_name == "subscription_cancelled":
        user.plan = "free_trial"
        user.subscription_status = "canceled"
        db.commit()
        logger.info("[Billing] Abonnement annulé | user=%s", user.email)

    elif event_name == "subscription_payment_failed":
        user.subscription_status = "past_due"
        db.commit()
        logger.warning("[Billing] Paiement échoué | user=%s", user.email)

    return {"received": True}
