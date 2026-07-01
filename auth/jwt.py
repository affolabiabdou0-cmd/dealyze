"""JWT token creation and decoding."""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from config.settings import settings


# --------------------------------------------------------------------------- #
# Password helpers                                                             #
# --------------------------------------------------------------------------- #

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# --------------------------------------------------------------------------- #
# Token helpers                                                                #
# --------------------------------------------------------------------------- #

def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Returns the payload dict or raises JWTError if invalid / expired.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
