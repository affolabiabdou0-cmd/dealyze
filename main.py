"""
Dealyze — FastAPI Backend
Entry point: uvicorn main:app --reload
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from auth.jwt import create_access_token, hash_password, verify_password
from auth.quota import check_quota, PLAN_LIMITS
from config.settings import settings
from models.database import create_tables, get_db
from models.schemas import (
    Chase, DueReport, Quote, RadarReport,
    save_chase, save_due, save_quote, save_radar,
)
from models.user import User, create_user, get_user_by_email
from routers.billing import router as billing_router
from utils.logger import setup_logging
from utils.pdf_reader import extract_text
from agents.deal_draft import DealDraftAgent, DealDraftInput
from agents.smart_chase import SmartChaseAgent, SmartChaseInput, InvoiceData
from agents.pitch_radar import PitchRadarAgent, PitchRadarInput
from agents.deep_due import DeepDueAgent, DeepDueInput

setup_logging()
import logging
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# App lifecycle                                                                #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    logger.info("Dealyze API v%s — starting up [%s]", settings.app_version, settings.app_env)
    yield
    logger.info("Dealyze API — shutting down")


app = FastAPI(
    title="Dealyze API",
    description="Turn every deal into done. — AI agents for SMBs and investors.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_deal_draft_agent  = DealDraftAgent()
_smart_chase_agent = SmartChaseAgent()
_pitch_radar_agent = PitchRadarAgent()
_deep_due_agent    = DeepDueAgent()

app.include_router(billing_router, prefix="/billing", tags=["Facturation"])


# =========================================================================== #
# AUTH                                                                         #
# =========================================================================== #

class RegisterRequest(BaseModel):
    email:     EmailStr
    password:  str       = Field(..., min_length=8)
    full_name: str       = Field(..., min_length=2)
    profile:   str       = Field("pme")   # "pme" | "investisseur"


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      str
    email:        str
    full_name:    str
    profile:      str
    plan:         str


class UserMeResponse(BaseModel):
    user_id:    str
    email:      str
    full_name:  str
    profile:    str
    plan:       str
    created_at: str


@app.post("/auth/register", response_model=TokenResponse, tags=["Auth"])
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new account. Returns a JWT access token immediately."""
    if get_user_by_email(db, req.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email déjà utilisé.")

    if req.profile not in ("pme", "investisseur"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "profile doit être 'pme' ou 'investisseur'.")

    user_id = str(uuid.uuid4())
    user = create_user(
        db,
        user_id=user_id,
        email=req.email,
        full_name=req.full_name,
        hashed_password=hash_password(req.password),
        profile=req.profile,
    )
    token = create_access_token(user.id, user.email)
    logger.info("[Auth] New user registered: %s (%s)", user.email, user.profile)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        profile=user.profile,
        plan=user.plan,
    )


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login with email + password. Returns a JWT access token."""
    user = get_user_by_email(db, req.email)
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Email ou mot de passe incorrect.")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Compte désactivé.")

    token = create_access_token(user.id, user.email)
    logger.info("[Auth] Login: %s", user.email)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        profile=user.profile,
        plan=user.plan,
    )


@app.get("/auth/me", response_model=UserMeResponse, tags=["Auth"])
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return UserMeResponse(
        user_id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        profile=current_user.profile,
        plan=current_user.plan,
        created_at=current_user.created_at.isoformat(),
    )


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    profile:   str = Field(...) # "pme" | "investisseur"


@app.put("/auth/me", response_model=UserMeResponse, tags=["Auth"])
def update_profile(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Modifier son nom et son profil."""
    if req.profile not in ("pme", "investisseur"):
        raise HTTPException(422, "profile doit être 'pme' ou 'investisseur'.")
    current_user.full_name = req.full_name
    current_user.profile   = req.profile
    db.commit()
    db.refresh(current_user)
    return UserMeResponse(
        user_id=current_user.id, email=current_user.email,
        full_name=current_user.full_name, profile=current_user.profile,
        plan=current_user.plan, created_at=current_user.created_at.isoformat(),
    )


class ChangePasswordRequest(BaseModel):
    ancien_mot_de_passe: str
    nouveau_mot_de_passe: str = Field(..., min_length=8)


class GoogleAuthRequest(BaseModel):
    firebase_token: str
    profile: str = "pme"  # "pme" | "investisseur"


@app.post("/auth/google", response_model=TokenResponse, tags=["Auth"])
def google_login(req: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Connexion / inscription via Google OAuth (Firebase). Le frontend envoie le Firebase ID token."""
    try:
        from auth.firebase_client import verify_firebase_token
        decoded = verify_firebase_token(req.firebase_token)
    except Exception as e:
        logger.warning("[Auth] Firebase token invalid: %s", e)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token Firebase invalide ou expiré.")

    email = decoded.get("email")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email manquant dans le token Google.")

    full_name = decoded.get("name") or email.split("@")[0]
    profile = req.profile if req.profile in ("pme", "investisseur") else "pme"

    user = get_user_by_email(db, email)
    if not user:
        user = create_user(
            db,
            user_id=str(uuid.uuid4()),
            email=email,
            full_name=full_name,
            hashed_password="google_oauth",
            profile=profile,
        )
        logger.info("[Auth] New Google user registered: %s (%s)", email, profile)

    token = create_access_token(user.id, user.email)
    logger.info("[Auth] Google login: %s", email)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        profile=user.profile,
        plan=user.plan,
    )


@app.put("/auth/change-password", tags=["Auth"])
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Changer son mot de passe."""
    if not verify_password(req.ancien_mot_de_passe, current_user.hashed_password):
        raise HTTPException(401, "Ancien mot de passe incorrect.")
    current_user.hashed_password = hash_password(req.nouveau_mot_de_passe)
    db.commit()
    return {"message": "Mot de passe modifié avec succès."}


@app.get("/auth/quota", tags=["Auth"])
def my_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retourne l'usage mensuel de l'utilisateur et ses limites par agent."""
    from auth.quota import AGENT_TABLE, _start_of_month
    month_start = _start_of_month()
    limits = PLAN_LIMITS.get(current_user.plan, PLAN_LIMITS["free_trial"])
    result = {}
    for agent, table in AGENT_TABLE.items():
        used = db.query(table).filter(
            table.user_id == current_user.id,
            table.created_at >= month_start,
        ).count()
        limit = limits.get(agent, 0)
        result[agent] = {
            "utilisé": used,
            "limite": limit if limit != -1 else "illimité",
            "restant": max(0, limit - used) if limit != -1 else "illimité",
        }
    return {"plan": current_user.plan, "mois": str(month_start)[:7], "quotas": result}


# =========================================================================== #
# SYSTEM                                                                       #
# =========================================================================== #

@app.get("/health", tags=["System"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/stats", tags=["System"])
def stats(db: Session = Depends(get_db)):
    """Platform-wide metrics — hackathon proof of live usage."""
    quotes = db.query(func.count(Quote.id)).scalar()
    chases = db.query(func.count(Chase.id)).scalar()
    radars = db.query(func.count(RadarReport.id)).scalar()
    dues   = db.query(func.count(DueReport.id)).scalar()
    users  = db.query(func.count(User.id)).scalar()
    avg_score = db.query(func.avg(RadarReport.score_global)).scalar()

    last = db.query(Quote).order_by(Quote.created_at.desc()).first()
    return {
        "total_users": users,
        "total_agent_runs": quotes + chases + radars + dues,
        "deal_draft":   {"total_quotes": quotes},
        "smart_chase":  {"total_reminders": chases},
        "pitch_radar":  {"total_analyses": radars, "avg_score": round(avg_score, 1) if avg_score else None},
        "deep_due":     {"total_reports": dues},
        "last_activity": last.created_at.isoformat() if last else None,
    }


@app.get("/activity", tags=["System"])
def activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Last N agent runs for the authenticated user."""
    uid = current_user.id
    rows = []
    for r in db.query(Quote).filter(Quote.user_id == uid).order_by(Quote.created_at.desc()).limit(limit):
        rows.append({"agent": "Deal Draft",  "id": r.id, "detail": r.client_name, "at": r.created_at.isoformat()})
    for r in db.query(Chase).filter(Chase.user_id == uid).order_by(Chase.created_at.desc()).limit(limit):
        rows.append({"agent": "Smart Chase", "id": r.id, "detail": r.email_subject, "at": r.created_at.isoformat()})
    for r in db.query(RadarReport).filter(RadarReport.user_id == uid).order_by(RadarReport.created_at.desc()).limit(limit):
        rows.append({"agent": "Pitch Radar", "id": r.id, "detail": f"{r.startup_name} {r.score_global}/10", "at": r.created_at.isoformat()})
    for r in db.query(DueReport).filter(DueReport.user_id == uid).order_by(DueReport.created_at.desc()).limit(limit):
        rows.append({"agent": "Deep Due",    "id": r.id, "detail": r.company_name, "at": r.created_at.isoformat()})

    rows.sort(key=lambda x: x["at"], reverse=True)
    return rows[:limit]


# =========================================================================== #
# DEAL DRAFT                                                                   #
# =========================================================================== #

class DealDraftRequest(BaseModel):
    client_name: str = Field(..., example="TechStyle Paris")
    sector:      str = Field(..., example="Agence web / e-commerce")
    need:        str = Field(..., example="Création d'un site e-commerce")
    budget:      str = Field(..., example="8 000 €")
    timeline:    str = Field(..., example="6 semaines")
    language:    str = Field("fr")


class DealDraftResponse(BaseModel):
    quote_id: str; client_name: str; generated_at: str
    tone: str; language: str; content: dict


@app.post("/agents/deal-draft/generate", response_model=DealDraftResponse, tags=["Deal Draft"])
def generate_quote(
    req: DealDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_quota("deal_draft")),
):
    try:
        result = _deal_draft_agent.generate(DealDraftInput(
            client_name=req.client_name, sector=req.sector, need=req.need,
            budget=req.budget, timeline=req.timeline, language=req.language,
        ))
        save_quote(db, result, req, user_id=current_user.id)
        return DealDraftResponse(
            quote_id=result.quote_id, client_name=result.client_name,
            generated_at=result.generated_at, tone=result.tone,
            language=result.language, content=result.content,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DealDraft] %s", e); raise HTTPException(500, str(e))


@app.get("/agents/deal-draft/quotes", tags=["Deal Draft"])
def list_quotes(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Quote).filter(Quote.user_id == current_user.id)\
             .order_by(Quote.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "client_name": r.client_name, "sector": r.sector,
             "tone": r.tone, "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/agents/deal-draft/quotes/{quote_id}", tags=["Deal Draft"])
def get_quote(
    quote_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer un devis complet par son ID."""
    row = db.query(Quote).filter(Quote.id == quote_id, Quote.user_id == current_user.id).first()
    if not row:
        raise HTTPException(404, "Devis introuvable.")
    import json
    return {"id": row.id, "client_name": row.client_name, "sector": row.sector,
            "need": row.need, "budget": row.budget, "timeline": row.timeline,
            "tone": row.tone, "language": row.language,
            "content": json.loads(row.content_json),
            "created_at": row.created_at.isoformat()}


# =========================================================================== #
# SMART CHASE                                                                  #
# =========================================================================== #

class InvoiceRequest(BaseModel):
    invoice_id:         str   = Field(..., example="FAC-2026-042")
    client_name:        str   = Field(..., example="Dupont & Fils SARL")
    amount:             float = Field(..., example=3500.0)
    currency:           str   = Field("EUR")
    due_date:           str   = Field(..., example="2026-06-01")
    issue_date:         str   = Field(..., example="2026-05-01")
    description:        str   = Field("")
    previous_reminders: int   = Field(0)
    payment_history:    str   = Field("nouveau_client")


class SmartChaseRequest(BaseModel):
    invoice:      InvoiceRequest
    company_name: str = Field(..., example="Agence Nova")
    chase_style:  str = Field("professionnel")
    language:     str = Field("fr")


class SmartChaseResponse(BaseModel):
    chase_id: str; invoice_id: str; client_name: str
    amount_display: str; days_overdue: int; escalation_level: int
    client_profile: str; tone: str; email_subject: str
    email_body: str; next_action_date: str; generated_at: str


@app.post("/agents/smart-chase/generate", response_model=SmartChaseResponse, tags=["Smart Chase"])
def generate_reminder(
    req: SmartChaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_quota("smart_chase")),
):
    try:
        inv = req.invoice
        result = _smart_chase_agent.generate(SmartChaseInput(
            invoice=InvoiceData(
                invoice_id=inv.invoice_id, client_name=inv.client_name,
                amount=inv.amount, currency=inv.currency,
                due_date=inv.due_date, issue_date=inv.issue_date,
                description=inv.description,
                previous_reminders=inv.previous_reminders,
                payment_history=inv.payment_history,
            ),
            company_name=req.company_name,
            chase_style=req.chase_style,
            language=req.language,
        ))
        save_chase(db, result, req, user_id=current_user.id)
        return SmartChaseResponse(
            chase_id=result.chase_id, invoice_id=result.invoice_id,
            client_name=result.client_name, amount_display=result.amount_display,
            days_overdue=result.days_overdue, escalation_level=result.escalation_level,
            client_profile=result.client_profile, tone=result.tone,
            email_subject=result.email_subject, email_body=result.email_body,
            next_action_date=result.next_action_date, generated_at=result.generated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[SmartChase] %s", e); raise HTTPException(500, str(e))


@app.get("/agents/smart-chase/reminders", tags=["Smart Chase"])
def list_reminders(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Chase).filter(Chase.user_id == current_user.id)\
             .order_by(Chase.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "invoice_id": r.invoice_id, "client_name": r.client_name,
             "escalation_level": r.escalation_level, "email_subject": r.email_subject,
             "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/agents/smart-chase/reminders/{chase_id}", tags=["Smart Chase"])
def get_reminder(
    chase_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer une relance complète par son ID."""
    row = db.query(Chase).filter(Chase.id == chase_id, Chase.user_id == current_user.id).first()
    if not row:
        raise HTTPException(404, "Relance introuvable.")
    return {"id": row.id, "invoice_id": row.invoice_id, "client_name": row.client_name,
            "amount": row.amount, "currency": row.currency, "days_overdue": row.days_overdue,
            "escalation_level": row.escalation_level, "client_profile": row.client_profile,
            "tone": row.tone, "language": row.language,
            "email_subject": row.email_subject, "email_body": row.email_body,
            "next_action_date": row.next_action_date, "created_at": row.created_at.isoformat()}


# =========================================================================== #
# PITCH RADAR                                                                  #
# =========================================================================== #

class CriterionScoreResponse(BaseModel):
    key: str; label: str; score: float; weight: float; note: str


class PitchRadarResponse(BaseModel):
    radar_id: str; startup_name: str; generated_at: str; language: str
    scores: list[CriterionScoreResponse]; score_global: float
    points_forts: list[str]; points_alerte: list[str]
    questions_suggerees: list[str]; recommandation: str


@app.post("/agents/pitch-radar/analyze", response_model=PitchRadarResponse, tags=["Pitch Radar"])
async def analyze_pitch(
    startup_name: str             = Form(...),
    language:     str             = Form("fr"),
    deck_text:    str             = Form(""),
    file:         UploadFile | None = File(None),
    db:           Session         = Depends(get_db),
    current_user: User            = Depends(check_quota("pitch_radar")),
):
    try:
        text = deck_text
        if file:
            text = extract_text(await file.read())
        if not text.strip():
            raise HTTPException(400, "Fournir un PDF ou du texte.")

        result = _pitch_radar_agent.analyze(PitchRadarInput(
            deck_text=text, startup_name=startup_name, language=language,
        ))
        save_radar(db, result, user_id=current_user.id)
        return PitchRadarResponse(
            radar_id=result.radar_id, startup_name=result.startup_name,
            generated_at=result.generated_at, language=result.language,
            scores=[CriterionScoreResponse(
                key=s.key, label=s.label, score=s.score, weight=s.weight, note=s.note,
            ) for s in result.scores],
            score_global=result.score_global,
            points_forts=result.points_forts,
            points_alerte=result.points_alerte,
            questions_suggerees=result.questions_suggerees,
            recommandation=result.recommandation,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[PitchRadar] %s", e); raise HTTPException(500, str(e))


@app.get("/agents/pitch-radar/reports", tags=["Pitch Radar"])
def list_radars(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(RadarReport).filter(RadarReport.user_id == current_user.id)\
             .order_by(RadarReport.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "startup_name": r.startup_name, "score_global": r.score_global,
             "recommandation": r.recommandation, "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/agents/pitch-radar/reports/{radar_id}", tags=["Pitch Radar"])
def get_radar(
    radar_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer une analyse pitch complète par son ID."""
    import json
    row = db.query(RadarReport).filter(RadarReport.id == radar_id, RadarReport.user_id == current_user.id).first()
    if not row:
        raise HTTPException(404, "Rapport introuvable.")
    return {"id": row.id, "startup_name": row.startup_name, "score_global": row.score_global,
            "recommandation": row.recommandation, "language": row.language,
            "detail": json.loads(row.raw_json), "created_at": row.created_at.isoformat()}


# =========================================================================== #
# DEEP DUE                                                                     #
# =========================================================================== #

class DeepDueRequest(BaseModel):
    company_name: str = Field(..., example="Stripe")
    founder_name: str = Field("",  example="Patrick Collison")
    context:      str = Field("",  example="Paste public info here...")
    language:     str = Field("fr")


class RiskItemResponse(BaseModel):
    level: str; description: str


class FounderProfileResponse(BaseModel):
    resume: str; experience: str; reputation: str
    signaux_positifs: list[str]; signaux_negatifs: list[str]


class CompanyAnalysisResponse(BaseModel):
    resume: str; structure: str; position_marche: str
    concurrents: list[str]; risques: list[str]


class DeepDueResponse(BaseModel):
    due_id: str; company_name: str; founder_name: str
    generated_at: str; language: str; synthese_executive: str
    profil_fondateur: FounderProfileResponse
    analyse_entreprise: CompanyAnalysisResponse
    risques_identifies: list[RiskItemResponse]
    recommandation_finale: str; score_confiance: float


@app.post("/agents/deep-due/analyze", response_model=DeepDueResponse, tags=["Deep Due"])
def analyze_company(
    req: DeepDueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(check_quota("deep_due")),
):
    try:
        result = _deep_due_agent.analyze(DeepDueInput(
            company_name=req.company_name, founder_name=req.founder_name,
            context=req.context, language=req.language,
        ))
        save_due(db, result, user_id=current_user.id)
        return DeepDueResponse(
            due_id=result.due_id, company_name=result.company_name,
            founder_name=result.founder_name, generated_at=result.generated_at,
            language=result.language, synthese_executive=result.synthese_executive,
            profil_fondateur=FounderProfileResponse(
                resume=result.profil_fondateur.resume,
                experience=result.profil_fondateur.experience,
                reputation=result.profil_fondateur.reputation,
                signaux_positifs=result.profil_fondateur.signaux_positifs,
                signaux_negatifs=result.profil_fondateur.signaux_negatifs,
            ),
            analyse_entreprise=CompanyAnalysisResponse(
                resume=result.analyse_entreprise.resume,
                structure=result.analyse_entreprise.structure,
                position_marche=result.analyse_entreprise.position_marche,
                concurrents=result.analyse_entreprise.concurrents,
                risques=result.analyse_entreprise.risques,
            ),
            risques_identifies=[
                RiskItemResponse(level=r.level, description=r.description)
                for r in result.risques_identifies
            ],
            recommandation_finale=result.recommandation_finale,
            score_confiance=result.score_confiance,
        )
    except Exception as e:
        logger.error("[DeepDue] %s", e); raise HTTPException(500, str(e))


@app.get("/agents/deep-due/reports", tags=["Deep Due"])
def list_dues(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(DueReport).filter(DueReport.user_id == current_user.id)\
             .order_by(DueReport.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "company_name": r.company_name, "founder_name": r.founder_name,
             "score_confiance": r.score_confiance, "recommandation_finale": r.recommandation_finale,
             "created_at": r.created_at.isoformat()} for r in rows]


@app.get("/agents/deep-due/reports/{due_id}", tags=["Deep Due"])
def get_due(
    due_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer un rapport de due diligence complet par son ID."""
    import json
    row = db.query(DueReport).filter(DueReport.id == due_id, DueReport.user_id == current_user.id).first()
    if not row:
        raise HTTPException(404, "Rapport introuvable.")
    return {"id": row.id, "company_name": row.company_name, "founder_name": row.founder_name,
            "recommandation_finale": row.recommandation_finale, "score_confiance": row.score_confiance,
            "language": row.language, "detail": json.loads(row.raw_json),
            "created_at": row.created_at.isoformat()}
