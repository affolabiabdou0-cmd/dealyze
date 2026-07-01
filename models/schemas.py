"""
SQLAlchemy ORM models — one table per agent.
All tables include created_at for audit trail (required for hackathon proof).
"""
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Session

from models.database import Base


# --------------------------------------------------------------------------- #
# ORM models                                                                   #
# --------------------------------------------------------------------------- #

class Quote(Base):
    """Deal Draft — generated quotes."""
    __tablename__ = "quotes"

    id           = Column(String,  primary_key=True)
    user_id      = Column(String,  index=True, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, index=True)
    client_name  = Column(String)
    sector       = Column(String)
    need         = Column(Text)
    budget       = Column(String)
    timeline     = Column(String)
    tone         = Column(String)
    language     = Column(String)
    content_json = Column(Text)


class Chase(Base):
    """Smart Chase — payment reminder emails."""
    __tablename__ = "chases"

    id               = Column(String,  primary_key=True)
    user_id          = Column(String,  index=True, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, index=True)
    invoice_id       = Column(String)
    client_name      = Column(String)
    amount           = Column(Float)
    currency         = Column(String)
    days_overdue     = Column(Integer)
    escalation_level = Column(Integer)
    client_profile   = Column(String)
    tone             = Column(String)
    language         = Column(String)
    email_subject    = Column(String)
    email_body       = Column(Text)
    next_action_date = Column(String)


class RadarReport(Base):
    """Pitch Radar — pitch deck analyses."""
    __tablename__ = "radar_reports"

    id             = Column(String,  primary_key=True)
    user_id        = Column(String,  index=True, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, index=True)
    startup_name   = Column(String)
    score_global   = Column(Float)
    recommandation = Column(String)
    language       = Column(String)
    raw_json       = Column(Text)


class DueReport(Base):
    """Deep Due — due diligence reports."""
    __tablename__ = "due_reports"

    id                    = Column(String,  primary_key=True)
    user_id               = Column(String,  index=True, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow, index=True)
    company_name          = Column(String)
    founder_name          = Column(String)
    recommandation_finale = Column(String)
    score_confiance       = Column(Float)
    language              = Column(String)
    raw_json              = Column(Text)


# --------------------------------------------------------------------------- #
# Repository helpers (called from routes)                                      #
# --------------------------------------------------------------------------- #

def save_quote(db: Session, result, req, user_id: str | None = None) -> Quote:
    row = Quote(
        id=result.quote_id,
        user_id=user_id,
        client_name=result.client_name,
        sector=req.sector,
        need=req.need,
        budget=req.budget,
        timeline=req.timeline,
        tone=result.tone,
        language=result.language,
        content_json=json.dumps(result.content, ensure_ascii=False),
    )
    db.add(row); db.commit()
    return row


def save_chase(db: Session, result, req, user_id: str | None = None) -> Chase:
    row = Chase(
        id=result.chase_id,
        user_id=user_id,
        invoice_id=result.invoice_id,
        client_name=result.client_name,
        amount=req.invoice.amount,
        currency=req.invoice.currency,
        days_overdue=result.days_overdue,
        escalation_level=result.escalation_level,
        client_profile=result.client_profile,
        tone=result.tone,
        language=req.language,
        email_subject=result.email_subject,
        email_body=result.email_body,
        next_action_date=result.next_action_date,
    )
    db.add(row); db.commit()
    return row


def save_radar(db: Session, result, user_id: str | None = None) -> RadarReport:
    raw = {
        "scores": [
            {"key": s.key, "label": s.label, "score": s.score, "note": s.note}
            for s in result.scores
        ],
        "points_forts": result.points_forts,
        "points_alerte": result.points_alerte,
        "questions_suggerees": result.questions_suggerees,
    }
    row = RadarReport(
        id=result.radar_id,
        user_id=user_id,
        startup_name=result.startup_name,
        score_global=result.score_global,
        recommandation=result.recommandation,
        language=result.language,
        raw_json=json.dumps(raw, ensure_ascii=False),
    )
    db.add(row); db.commit()
    return row


def save_due(db: Session, result, user_id: str | None = None) -> DueReport:
    raw = {
        "synthese_executive": result.synthese_executive,
        "profil_fondateur": {
            "resume": result.profil_fondateur.resume,
            "signaux_positifs": result.profil_fondateur.signaux_positifs,
            "signaux_negatifs": result.profil_fondateur.signaux_negatifs,
        },
        "risques_identifies": [
            {"niveau": r.level, "description": r.description}
            for r in result.risques_identifies
        ],
    }
    row = DueReport(
        id=result.due_id,
        user_id=user_id,
        company_name=result.company_name,
        founder_name=result.founder_name,
        recommandation_finale=result.recommandation_finale,
        score_confiance=result.score_confiance,
        language=result.language,
        raw_json=json.dumps(raw, ensure_ascii=False),
    )
    db.add(row); db.commit()
    return row
