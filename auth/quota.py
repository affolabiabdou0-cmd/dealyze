"""
Vérification des quotas par plan.
Injecté comme dépendance FastAPI dans chaque route agent.
"""
from calendar import monthrange
from datetime import date
from functools import partial

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from models.database import get_db
from models.schemas import Chase, DueReport, Quote, RadarReport
from models.user import User

# -1 = illimité
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free_trial": {"deal_draft": 3,  "smart_chase": 3,  "pitch_radar": 1, "deep_due": 1},
    "starter":    {"deal_draft": 17, "smart_chase": 17, "pitch_radar": 5, "deep_due": 3},
    "growth":     {"deal_draft": -1, "smart_chase": -1, "pitch_radar": -1, "deep_due": -1},
    "enterprise": {"deal_draft": -1, "smart_chase": -1, "pitch_radar": -1, "deep_due": -1},
}

AGENT_TABLE = {
    "deal_draft":  Quote,
    "smart_chase": Chase,
    "pitch_radar": RadarReport,
    "deep_due":    DueReport,
}


def _start_of_month() -> date:
    today = date.today()
    return today.replace(day=1)


def check_quota(agent: str):
    """
    Retourne une dépendance FastAPI qui vérifie le quota mensuel de l'utilisateur.
    Usage : Depends(check_quota("deal_draft"))
    """
    def _check(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        plan = current_user.plan
        limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free_trial"]).get(agent, 0)

        if limit == -1:
            return current_user  # illimité

        table = AGENT_TABLE[agent]
        month_start = _start_of_month()

        used = (
            db.query(table)
            .filter(
                table.user_id == current_user.id,
                table.created_at >= month_start,
            )
            .count()
        )

        if used >= limit:
            plan_nom = plan.replace("_", " ").title()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Quota atteint pour ce mois ({used}/{limit} sur le plan {plan_nom}). "
                    f"Passez au plan supérieur sur /billing/checkout."
                ),
            )
        return current_user

    return _check
