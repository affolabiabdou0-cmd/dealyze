"""Firebase Admin SDK — initialisation et vérification des tokens Google."""
import json
import os

import firebase_admin
from firebase_admin import auth, credentials

_app = None


def _get_app():
    global _app
    if _app is not None:
        return _app
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise EnvironmentError("FIREBASE_SERVICE_ACCOUNT_JSON not set")
    info = json.loads(raw)
    cred = credentials.Certificate(info)
    _app = firebase_admin.initialize_app(cred)
    return _app


def verify_firebase_token(id_token: str) -> dict:
    """Vérifie un token Firebase ID et retourne le payload décodé."""
    _get_app()
    return auth.verify_id_token(id_token)
