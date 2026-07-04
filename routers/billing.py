"""
VYXEN — Facturation Paddle
Routes : /billing/*
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

PADDLE_API = "https://api.paddle.com"

# ─── Plans ───────────────────────────────────────────────────────────────────

PLANS = {
    "starter": {
        "nom": "Starter", "prix": 47, "devise": "USD",
        "price_id": settings.paddle_price_starter,
        "description": "Pour les PME qui démarrent",
    },
    "growth": {
        "nom": "Growth", "prix": 147, "devise": "USD",
        "price_id": settings.paddle_price_growth,
        "description": "Pour les équipes en croissance",
    },
    "enterprise": {
        "nom": "Enterprise", "prix": 477, "devise": "USD",
        "price_id": settings.paddle_price_enterprise,
        "description": "Pour les fonds et cabinets",
    },
}


def _paddle_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
    }


def _verify_paddle_signature(payload: bytes, signature_header: str) -> bool:
    """Vérifie la signature HMAC-SHA256 du webhook Paddle."""
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(";"))
        ts = parts.get("ts", "")
        h1 = parts.get("h1", "")
        signed = f"{ts}:{payload.decode()}"
        expected = hmac.new(
            settings.paddle_webhook_secret.encode(),
            signed.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, h1)
    except Exception:
        return False


# ─── GET /billing/plans ───────────────────────────────────────────────────────

@router.get("/plans")
def list_plans():
    return [
        {
            "plan_id": key,
            "nom": p["nom"],
            "prix_mensuel": p["prix"],
            "devise": p["devise"],
            "description": p["description"],
        }
        for key, p in PLANS.items()
    ]


# ─── GET /billing/mode ────────────────────────────────────────────────────────

@router.get("/mode")
def billing_mode():
    return {
        "mode": "simulation" if settings.simulation_mode else "production",
        "provider": "Paddle" if not settings.simulation_mode else "N/A",
        "configured": bool(settings.paddle_api_key) or settings.simulation_mode,
    }


# ─── POST /billing/checkout ───────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str


@router.post("/checkout")
def create_checkout(
    req: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = PLANS.get(req.plan)
    if not plan:
        raise HTTPException(422, f"Plan inconnu : {req.plan}")

    # ── Simulation ────────────────────────────────────────────────────────────
    if settings.simulation_mode:
        sim_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
        update_user_subscription(
            db, current_user,
            plan=req.plan,
            stripe_customer_id=f"sim_cust_{current_user.id[:8]}",
            stripe_subscription_id=sim_id,
            subscription_status="active",
        )
        logger.info("[Billing-SIM] Plan simulé | user=%s | plan=%s", current_user.email, req.plan)
        return {
            "mode": "simulation",
            "checkout_url": f"/dashboard?payment=simulated&plan={req.plan}",
            "plan_active": req.plan,
        }

    # ── Production Paddle ─────────────────────────────────────────────────────
    if not settings.paddle_api_key:
        raise HTTPException(503, "PADDLE_API_KEY non configuré sur Render.")

    if not plan["price_id"]:
        raise HTTPException(503, f"PADDLE_PRICE_{req.plan.upper()} non configuré sur Render.")

    # Retourne le price_id — le frontend ouvre le checkout Paddle.js
    return {
        "mode": "production",
        "price_id": plan["price_id"],
        "plan": req.plan,
        "user_id": current_user.id,
        "user_email": current_user.email,
    }


# ─── POST /billing/simulate-upgrade ──────────────────────────────────────────

class SimulateUpgradeRequest(BaseModel):
    plan: str
    status: str = "active"


@router.post("/simulate-upgrade")
def simulate_upgrade(
    req: SimulateUpgradeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    return {"message": f"Plan changé en {req.plan}", "plan": req.plan, "status": req.status}


# ─── GET /billing/subscription ────────────────────────────────────────────────

@router.get("/subscription")
def get_subscription(current_user: User = Depends(get_current_user)):
    plan_info = PLANS.get(current_user.plan)
    return {
        "plan": current_user.plan,
        "plan_nom": plan_info["nom"] if plan_info else "Essai gratuit",
        "subscription_status": current_user.subscription_status,
        "paddle_customer_id": current_user.stripe_customer_id,
        "paddle_subscription_id": current_user.stripe_subscription_id,
    }


# ─── POST /billing/webhook ────────────────────────────────────────────────────

@router.post("/webhook")
async def paddle_webhook(
    request: Request,
    paddle_signature: str = Header(None, alias="paddle-signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()

    if settings.paddle_webhook_secret and paddle_signature:
        if not _verify_paddle_signature(payload, paddle_signature):
            logger.warning("[Paddle] Webhook : signature invalide")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature invalide.")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "Payload JSON invalide.")

    event_type = event.get("event_type", "")
    data = event.get("data", {})
    custom_data = data.get("custom_data") or {}
    user_id = custom_data.get("user_id")

    logger.info("[Paddle] Webhook reçu : %s | user_id=%s", event_type, user_id)

    if not user_id:
        return {"received": True}

    user = get_user_by_id(db, user_id)
    if not user:
        return {"received": True}

    if event_type in ("transaction.completed", "subscription.created", "subscription.updated"):
        # Récupère le plan depuis le price_id
        items = data.get("items", [])
        price_id = items[0].get("price", {}).get("id", "") if items else ""
        plan = "starter"
        for key, p in PLANS.items():
            if p["price_id"] == price_id:
                plan = key
                break

        paddle_customer_id = data.get("customer_id", "")
        paddle_sub_id = data.get("id", "")
        sub_status = data.get("status", "active")

        update_user_subscription(
            db, user,
            plan=plan,
            stripe_customer_id=str(paddle_customer_id),
            stripe_subscription_id=str(paddle_sub_id),
            subscription_status=sub_status,
        )
        logger.info("[Billing] Plan activé | user=%s | plan=%s", user.email, plan)

    elif event_type == "subscription.canceled":
        user.plan = "free_trial"
        user.subscription_status = "canceled"
        db.commit()
        logger.info("[Billing] Abonnement annulé | user=%s", user.email)

    elif event_type == "subscription.past_due":
        user.subscription_status = "past_due"
        db.commit()

    return {"received": True}
