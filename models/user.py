"""User ORM model + CRUD helpers."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import Session

from models.database import Base


class User(Base):
    __tablename__ = "users"

    id               = Column(String, primary_key=True)
    email            = Column(String, unique=True, index=True, nullable=False)
    full_name        = Column(String, nullable=False)
    hashed_password  = Column(String, nullable=False)
    profile          = Column(String, default="pme")        # "pme" | "investisseur"
    plan             = Column(String, default="free_trial") # "free_trial" | "starter" | "growth" | "enterprise"
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    # Stripe
    stripe_customer_id     = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    subscription_status    = Column(String, default="trialing")
    # "trialing" | "active" | "past_due" | "canceled" | "unpaid"
    current_period_end     = Column(DateTime, nullable=True)  # fin du cycle de facturation Paddle en cours


# --------------------------------------------------------------------------- #
# CRUD                                                                         #
# --------------------------------------------------------------------------- #

def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_stripe_customer(db: Session, customer_id: str) -> User | None:
    return db.query(User).filter(User.stripe_customer_id == customer_id).first()


def create_user(
    db: Session,
    user_id: str,
    email: str,
    full_name: str,
    hashed_password: str,
    profile: str = "pme",
) -> User:
    user = User(
        id=user_id,
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        profile=profile,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_subscription(
    db: Session,
    user: User,
    plan: str,
    stripe_customer_id: str,
    stripe_subscription_id: str,
    subscription_status: str,
    current_period_end: datetime | None = None,
) -> User:
    user.plan = plan
    user.stripe_customer_id = stripe_customer_id
    user.stripe_subscription_id = stripe_subscription_id
    user.subscription_status = subscription_status
    if current_period_end is not None:
        user.current_period_end = current_period_end
    db.commit()
    db.refresh(user)
    return user
