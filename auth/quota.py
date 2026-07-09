"""
Vérification des quotas par plan.
Injecté comme dépendance FastAPI dans chaque route agent.
"""
from calendar import monthrange
from datetime import date, datetime
from functools import partial

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from models.database import get_db
from models.schemas import Chase, DueReport, Quote, RadarReport
from models.user import User

# -1 = illimité, 0 = aucun accès
PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free_trial": {"deal_draft": 3,  "smart_chase": 5,  "pitch_radar": 2, "deep_due": 1},
    "starter":    {"deal_draft": 17, "smart_chase": 17, "pitch_radar": 5, "deep_due": 0},
    "growth":     {"deal_draft": -1, "smart_chase": -1, "pitch_radar": -1, "deep_due": 5},
    "enterprise": {"deal_draft": -1, "smart_chase": -1, "pitch_radar": -1, "deep_due": -1},
}

TRIAL_DURATION_DAYS = 14


def trial_days_remaining(created_at: datetime) -> int:
    """Jours restants sur l'essai gratuit de 14 jours (0 si expiré)."""
    elapsed = (datetime.utcnow() - created_at).days
    return max(0, TRIAL_DURATION_DAYS - elapsed)

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

        if plan == "free_trial" and trial_days_remaining(current_user.created_at) <= 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Votre essai gratuit de 14 jours est terminé. Passez à un plan payant sur /billing/checkout pour continuer.",
            )

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
            if limit == 0:
                msg = f"Cet agent n'est pas disponible sur le plan {plan_nom}. Passez au plan supérieur sur /billing/checkout."
            else:
                msg = f"Quota atteint pour ce mois ({used}/{limit} sur le plan {plan_nom}). Passez au plan supérieur sur /billing/checkout."
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )
        return current_user

    return _check
