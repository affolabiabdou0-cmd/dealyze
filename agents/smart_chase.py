import json
import re
import logging
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from agents.gemini_client import get_gemini_model

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Data models                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class InvoiceData:
    invoice_id: str
    client_name: str
    amount: float
    currency: str            # "EUR", "USD", "GBP", "CAD"
    due_date: str            # ISO "YYYY-MM-DD"
    issue_date: str          # ISO "YYYY-MM-DD"
    description: str = ""
    previous_reminders: int = 0
    payment_history: str = "nouveau_client"  # "bon_payeur" | "mauvais_payeur" | "nouveau_client"


@dataclass
class SmartChaseInput:
    invoice: InvoiceData
    company_name: str        # PME using VYXEN
    chase_style: str = "professionnel"   # "bienveillant" | "professionnel" | "ferme"
    language: str = "fr"


@dataclass
class SmartChaseOutput:
    chase_id: str
    invoice_id: str
    client_name: str
    amount_display: str
    days_overdue: int
    escalation_level: int    # 1 → 4
    client_profile: str
    tone: str
    email_subject: str
    email_body: str
    next_action_date: str    # ISO date
    generated_at: str
    raw_response: str


# --------------------------------------------------------------------------- #
# Business logic                                                               #
# --------------------------------------------------------------------------- #

def _days_overdue(due_date_str: str) -> int:
    due = date.fromisoformat(due_date_str)
    return max(0, (date.today() - due).days)


def _escalation_level(days_overdue: int, previous_reminders: int, payment_history: str) -> int:
    """
    Level 1 — Friendly reminder   (J+0 to J+7,  0 reminders sent)
    Level 2 — Firm follow-up      (J+8 to J+14, 1 reminder sent)
    Level 3 — Formal notice       (J+15 to J+30, 2 reminders sent)
    Level 4 — Alert / legal       (J+30+, 3+ reminders sent)
    """
    if previous_reminders >= 3 or days_overdue > 45:
        return 4
    if previous_reminders == 2 or days_overdue >= 30:
        return 3
    if previous_reminders == 1 or days_overdue >= 14:
        return 2
    # Bad payers escalate one level sooner
    if payment_history == "mauvais_payeur" and days_overdue >= 7:
        return 2
    return 1


def _detect_tone(level: int, payment_history: str, chase_style: str) -> str:
    if level == 4:
        return "très ferme, mise en demeure imminente"
    if level == 3:
        return "formel et sans ambiguïté" if payment_history != "bon_payeur" else "formel mais compréhensif"
    if level == 2:
        if payment_history == "bon_payeur":
            return "compréhensif mais clair"
        if payment_history == "mauvais_payeur":
            return "ferme et assertif"
        return "assertif"
    # Level 1
    if chase_style == "bienveillant" or payment_history == "bon_payeur":
        return "chaleureux et bienveillant"
    if chase_style == "ferme" or payment_history == "mauvais_payeur":
        return "poli mais direct"
    return "bienveillant et professionnel"


def _next_action_date(level: int) -> str:
    today = date.today()
    delays = {1: 7, 2: 7, 3: 15, 4: 0}
    return (today + timedelta(days=delays[level])).isoformat()


def _format_amount(amount: float, currency: str) -> str:
    prefix = {"USD": "$", "CAD": "CA$", "GBP": "£"}
    if currency in prefix:
        return f"{prefix[currency]}{amount:,.2f}"
    return f"{amount:,.2f} {currency}"


# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

_LEVEL_CTX_FR = {
    1: "Premier rappel amical — le client a probablement oublié ou l'email s'est perdu",
    2: "Deuxième relance — le retard est avéré, le ton doit être plus direct",
    3: "Mise en demeure — le retard est sérieux, le vocabulaire doit être formel",
    4: "Alerte critique — retard excessif, préparer une action formelle si nécessaire",
}

_LEVEL_CTX_EN = {
    1: "First friendly reminder — client likely forgot or email got lost",
    2: "Second follow-up — the delay is confirmed, be more direct",
    3: "Formal notice — serious delay, use formal language",
    4: "Critical alert — excessive delay, prepare formal action if needed",
}


def _build_system_prompt(language: str) -> str:
    if language == "fr":
        return """Tu es Smart Chase, l'agent IA de VYXEN. Tu rédiges des emails de relance impayée professionnels, humains et efficaces.

RÈGLES ABSOLUES :
— Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après
— L'email doit sonner humain, jamais robotique ni template générique
— Mentionner toujours le numéro de facture, le montant exact et la date d'échéance
— Laisser toujours une porte de sortie élégante ("si vous avez déjà effectué ce virement, veuillez ignorer ce message")
— Ne jamais menacer directement — rester professionnel quelle que soit la situation
— Signer au nom de l'entreprise expéditrice

FORMAT DE SORTIE :
{
  "objet": "Objet court et percutant (max 60 caractères)",
  "corps": "Corps complet de l'email avec sauts de ligne \\n entre les paragraphes"
}"""
    else:
        return """You are Smart Chase, VYXEN's AI agent. You write professional, human, and effective payment reminder emails.

ABSOLUTE RULES:
— Reply ONLY with a valid JSON object, no text before or after
— The email must sound human, never robotic or template-like
— Always mention the invoice number, exact amount, and due date
— Always include a graceful out ("If you've already sent payment, please disregard this message")
— Never threaten directly — stay professional regardless of the situation
— Sign on behalf of the sender company

OUTPUT FORMAT:
{
  "objet": "Short impactful subject line (max 60 chars)",
  "corps": "Full email body with \\n line breaks between paragraphs"
}"""


def _build_user_prompt(
    inputs: SmartChaseInput,
    days_overdue: int,
    level: int,
    tone: str,
    amount_display: str,
) -> str:
    inv = inputs.invoice
    if inputs.language == "fr":
        return (
            f"Rédige la relance pour cette facture :\n\n"
            f"EXPÉDITEUR : {inputs.company_name}\n"
            f"CLIENT : {inv.client_name}\n"
            f"FACTURE N° : {inv.invoice_id}\n"
            f"MONTANT DÛ : {amount_display}\n"
            f"DATE D'ÉCHÉANCE : {inv.due_date}\n"
            f"RETARD : {days_overdue} jour(s)\n"
            f"PRESTATION : {inv.description or 'Prestation selon devis'}\n"
            f"PROFIL CLIENT : {inv.payment_history}\n"
            f"RELANCES DÉJÀ ENVOYÉES : {inv.previous_reminders}\n\n"
            f"NIVEAU D'ESCALADE : {level}/4 — {_LEVEL_CTX_FR[level]}\n"
            f"TON : {tone}\n\n"
            f"Génère maintenant le JSON (objet + corps)."
        )
    else:
        return (
            f"Write the reminder for this invoice:\n\n"
            f"SENDER: {inputs.company_name}\n"
            f"CLIENT: {inv.client_name}\n"
            f"INVOICE #: {inv.invoice_id}\n"
            f"AMOUNT DUE: {amount_display}\n"
            f"DUE DATE: {inv.due_date}\n"
            f"DAYS OVERDUE: {days_overdue}\n"
            f"SERVICE: {inv.description or 'Services per agreement'}\n"
            f"CLIENT PROFILE: {inv.payment_history}\n"
            f"REMINDERS SENT: {inv.previous_reminders}\n\n"
            f"ESCALATION LEVEL: {level}/4 — {_LEVEL_CTX_EN[level]}\n"
            f"TONE: {tone}\n\n"
            f"Now generate the JSON (objet + corps)."
        )


# --------------------------------------------------------------------------- #
# JSON parsing                                                                 #
# --------------------------------------------------------------------------- #

def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("[SmartChase] JSON parsing failed — using raw text as body")
    return {"objet": "Relance facture", "corps": raw}


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #

class SmartChaseAgent:
    """
    Generates intelligent payment reminder emails.
    Adapts tone based on client profile, escalation level, and user style preference.
    """

    def __init__(self):
        self.model = get_gemini_model("gemini-2.5-flash")

    def generate(self, inputs: SmartChaseInput) -> SmartChaseOutput:
        inv = inputs.invoice
        days_overdue   = _days_overdue(inv.due_date)
        level          = _escalation_level(days_overdue, inv.previous_reminders, inv.payment_history)
        tone           = _detect_tone(level, inv.payment_history, inputs.chase_style)
        amount_display = _format_amount(inv.amount, inv.currency)
        next_date      = _next_action_date(level)
        chase_id       = f"SC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        logger.info(
            "[SmartChase] START | id=%s | client=%s | invoice=%s | overdue=%dd | level=%d | tone=%s",
            chase_id, inv.client_name, inv.invoice_id, days_overdue, level, tone,
        )

        prompt = _build_system_prompt(inputs.language) + "\n\n" + _build_user_prompt(inputs, days_overdue, level, tone, amount_display)
        response = self.model.generate_content(prompt)
        raw    = response.text
        parsed = _parse_json(raw)

        logger.info("[SmartChase] DONE | id=%s | level=%d | next_action=%s", chase_id, level, next_date)

        return SmartChaseOutput(
            chase_id=chase_id,
            invoice_id=inv.invoice_id,
            client_name=inv.client_name,
            amount_display=amount_display,
            days_overdue=days_overdue,
            escalation_level=level,
            client_profile=inv.payment_history,
            tone=tone,
            email_subject=parsed.get("objet", ""),
            email_body=parsed.get("corps", ""),
            next_action_date=next_date,
            generated_at=datetime.now().isoformat(),
            raw_response=raw,
        )
