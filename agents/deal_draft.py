import os
import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Data models                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class DealDraftInput:
    client_name: str      # 1. Nom du client / prospect
    sector: str           # 2. Secteur d'activité du client
    need: str             # 3. Besoin / mission à couvrir
    budget: str           # 4. Budget estimé
    timeline: str         # 5. Délai souhaité
    language: str = "fr"  # "fr" ou "en"


@dataclass
class DealDraftOutput:
    quote_id: str
    client_name: str
    generated_at: str
    tone: str
    language: str
    content: dict         # sections structurées du devis
    raw_response: str     # réponse brute LLM (pour logs / debug)


# --------------------------------------------------------------------------- #
# Tone detection                                                               #
# --------------------------------------------------------------------------- #

_FORMAL_KEYWORDS = {
    "juridique", "law", "notaire", "notary", "comptable", "accounting",
    "finance", "audit", "assurance", "insurance", "cabinet", "conseil",
    "consulting", "banque", "bank", "immobilier", "real estate",
}

_DYNAMIC_KEYWORDS = {
    "startup", "tech", "digital", "marketing", "communication", "web",
    "agence", "agency", "créatif", "creative", "media", "saas", "app",
    "e-commerce", "ecommerce", "growth",
}


def _detect_tone(sector: str) -> str:
    s = sector.lower()
    if any(k in s for k in _FORMAL_KEYWORDS):
        return "formel"
    if any(k in s for k in _DYNAMIC_KEYWORDS):
        return "dynamique"
    return "professionnel"


# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

_TONE_LABELS_FR = {
    "formel": (
        "FORMEL — vouvoiement systématique, formulations précises et réservées, "
        "vocabulaire professionnel soutenu."
    ),
    "dynamique": (
        "DYNAMIQUE — style direct et énergique, formulations orientées résultat, "
        "tu peux tutoyer ou utiliser un ton affirmé."
    ),
    "professionnel": (
        "PROFESSIONNEL — équilibré, vouvoiement, clair et orienté valeur, "
        "ni trop formel ni trop décontracté."
    ),
}

_TONE_LABELS_EN = {
    "formel": (
        "FORMAL — precise and reserved formulations, elevated professional vocabulary."
    ),
    "dynamique": (
        "DYNAMIC — direct, energetic, result-oriented phrasing."
    ),
    "professionnel": (
        "PROFESSIONAL — balanced, clear, value-oriented, neither stiff nor casual."
    ),
}

_JSON_SCHEMA = """{
  "titre": "Titre accrocheur du devis / de la proposition",
  "introduction": "Présentation personnalisée, accroche qui montre qu'on connaît leur contexte",
  "comprehension_besoin": "Reformulation précise du besoin qui prouve qu'on a tout compris",
  "solution_proposee": "Description de la solution avec bénéfices concrets et différenciants",
  "livrables": ["livrable précis 1", "livrable précis 2", "livrable précis 3"],
  "timeline": "Calendrier de réalisation phase par phase",
  "investissement": "Présentation valorisante du prix comme un investissement, pas un coût",
  "conditions": "Modalités de paiement, révisions incluses, garanties offertes",
  "conclusion": "Call-to-action percutant pour inciter à signer rapidement"
}"""

_JSON_SCHEMA_EN = """{
  "titre": "Catchy quote / proposal title",
  "introduction": "Personalized introduction that shows you understand their context",
  "comprehension_besoin": "Precise reformulation of the need proving you got it",
  "solution_proposee": "Solution description with concrete differentiating benefits",
  "livrables": ["precise deliverable 1", "precise deliverable 2", "precise deliverable 3"],
  "timeline": "Phase-by-phase implementation schedule",
  "investissement": "Value-framed price presentation — investment, not cost",
  "conditions": "Payment terms, included revisions, guarantees",
  "conclusion": "Strong call-to-action to drive quick signature"
}"""


def _build_system_prompt(tone: str, language: str) -> str:
    if language == "fr":
        return f"""Tu es Deal Draft, l'agent IA de Dealyze. Tu génères des devis et propositions commerciales professionnels, convaincants et personnalisés.

TON : {_TONE_LABELS_FR.get(tone, _TONE_LABELS_FR['professionnel'])}

RÈGLES ABSOLUES :
— Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après
— Sois spécifique : zéro phrase générique, tout doit coller au contexte fourni
— Les livrables doivent être concrets et mesurables (pas "suivi de projet")
— L'investissement doit être encadré comme une valeur, pas un coût brut
— 100 mots maximum par section

FORMAT DE SORTIE :
{_JSON_SCHEMA}"""
    else:
        return f"""You are Deal Draft, Dealyze's AI agent. You generate professional, convincing, personalized quotes and commercial proposals.

TONE: {_TONE_LABELS_EN.get(tone, _TONE_LABELS_EN['professionnel'])}

ABSOLUTE RULES:
— Reply ONLY with a valid JSON object, no text before or after
— Be specific: zero generic sentences, everything must fit the context given
— Deliverables must be concrete and measurable
— Investment must be framed as value, not a raw cost
— 100 words max per section

OUTPUT FORMAT:
{_JSON_SCHEMA_EN}"""


def _build_user_prompt(inputs: DealDraftInput, tone: str) -> str:
    if inputs.language == "fr":
        return (
            f"Génère le devis pour ces 5 informations :\n\n"
            f"CLIENT : {inputs.client_name}\n"
            f"SECTEUR : {inputs.sector}\n"
            f"BESOIN : {inputs.need}\n"
            f"BUDGET ESTIMÉ : {inputs.budget}\n"
            f"DÉLAI SOUHAITÉ : {inputs.timeline}\n\n"
            f"TON APPLIQUÉ : {tone}\n\n"
            f"Génère maintenant le JSON complet."
        )
    else:
        return (
            f"Generate the quote for these 5 inputs:\n\n"
            f"CLIENT: {inputs.client_name}\n"
            f"SECTOR: {inputs.sector}\n"
            f"NEED: {inputs.need}\n"
            f"ESTIMATED BUDGET: {inputs.budget}\n"
            f"DESIRED TIMELINE: {inputs.timeline}\n\n"
            f"APPLIED TONE: {tone}\n\n"
            f"Now generate the complete JSON."
        )


# --------------------------------------------------------------------------- #
# JSON parsing                                                                 #
# --------------------------------------------------------------------------- #

def _parse_json(raw: str) -> dict:
    """Extract and parse the first JSON object found in the LLM response."""
    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Extract content between first { and last }
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("[DealDraft] JSON parsing failed — storing raw response")
    return {"raw": raw}


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #

class DealDraftAgent:
    """
    Generates professional B2B quotes from 5 user inputs.
    Uses Groq (llama-3.3-70b-versatile) under the hood.
    """

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def generate(self, inputs: DealDraftInput) -> DealDraftOutput:
        tone = _detect_tone(inputs.sector)
        quote_id = f"DD-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        logger.info(
            "[DealDraft] START | id=%s | client=%s | sector=%s | tone=%s | lang=%s",
            quote_id, inputs.client_name, inputs.sector, tone, inputs.language,
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _build_system_prompt(tone, inputs.language)},
                {"role": "user",   "content": _build_user_prompt(inputs, tone)},
            ],
            temperature=0.7,
            max_tokens=2048,
        )

        raw = response.choices[0].message.content
        content = _parse_json(raw)

        logger.info(
            "[DealDraft] DONE  | id=%s | tokens_used=%s",
            quote_id,
            response.usage.total_tokens if response.usage else "N/A",
        )

        return DealDraftOutput(
            quote_id=quote_id,
            client_name=inputs.client_name,
            generated_at=datetime.now().isoformat(),
            tone=tone,
            language=inputs.language,
            content=content,
            raw_response=raw,
        )
