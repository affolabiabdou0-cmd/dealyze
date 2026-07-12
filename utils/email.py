"""Envoi d'emails transactionnels (mot de passe oublié, vérification de compte).

Si aucun SMTP n'est configuré (smtp_host vide), l'email n'est pas envoyé — le lien est
seulement loggé. Ça permet au reste de l'app (inscription, reset) de fonctionner sans
bloquer sur une dépendance externe non encore configurée.

Resend passe par son API HTTP plutôt que par SMTP : sur Render, les connexions SMTP
sortantes (port 587) échouaient systématiquement en timeout (confirmé en logs — pas un
souci Resend, une restriction réseau côté hébergeur, fréquente sur les plateformes cloud
gratuites). L'API HTTP utilise le port 443, jamais bloqué.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Envoie un email HTML. Retourne True si envoyé, False si non configuré ou en échec."""
    if not settings.smtp_host:
        logger.warning("[Email] Email non configuré — email à %s non envoyé (sujet: %s)", to, subject)
        return False

    if "resend.com" in settings.smtp_host:
        return _send_via_resend_api(to, subject, html_body)
    return _send_via_smtp(to, subject, html_body)


def _send_via_resend_api(to: str, subject: str, html_body: str) -> bool:
    try:
        res = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.smtp_password}"},
            json={"from": settings.smtp_from, "to": [to], "subject": subject, "html": html_body},
            timeout=10,
        )
        res.raise_for_status()
        logger.info("[Email] Envoyé via Resend à %s (sujet: %s)", to, subject)
        return True
    except httpx.HTTPError as e:
        detail = e.response.text if isinstance(e, httpx.HTTPStatusError) else str(e)
        logger.error("[Email] Échec d'envoi via Resend à %s : %s", to, detail)
        return False


def _send_via_smtp(to: str, subject: str, html_body: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [to], msg.as_string())
        logger.info("[Email] Envoyé via SMTP à %s (sujet: %s)", to, subject)
        return True
    except Exception as e:
        logger.error("[Email] Échec d'envoi via SMTP à %s : %s", to, e)
        return False


def send_password_reset_email(to: str, full_name: str, reset_link: str) -> bool:
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px;">
      <h2 style="color: #171321;">Réinitialisation de mot de passe</h2>
      <p style="color: #5b5570; font-size: 15px; line-height: 1.6;">
        Bonjour {full_name},<br><br>
        Une demande de réinitialisation de mot de passe a été faite pour votre compte VYXEN.
        Ce lien est valable 1 heure.
      </p>
      <a href="{reset_link}" style="display:inline-block; background:#7c3aed; color:#fff; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600; margin: 16px 0;">
        Réinitialiser mon mot de passe
      </a>
      <p style="color: #928cab; font-size: 13px;">
        Si vous n'êtes pas à l'origine de cette demande, ignorez simplement cet email — votre mot de passe reste inchangé.
      </p>
    </div>
    """
    return send_email(to, "Réinitialisation de votre mot de passe VYXEN", html)


def send_verification_email(to: str, full_name: str, verify_link: str) -> bool:
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px;">
      <h2 style="color: #171321;">Confirmez votre adresse email</h2>
      <p style="color: #5b5570; font-size: 15px; line-height: 1.6;">
        Bienvenue {full_name} !<br><br>
        Confirmez votre adresse email pour activer pleinement votre compte VYXEN.
      </p>
      <a href="{verify_link}" style="display:inline-block; background:#7c3aed; color:#fff; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:600; margin: 16px 0;">
        Confirmer mon email
      </a>
    </div>
    """
    return send_email(to, "Confirmez votre adresse email VYXEN", html)
