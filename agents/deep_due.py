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
class DeepDueInput:
    company_name: str
    founder_name: str = ""
    context: str = ""       # optional: user pastes info found (LinkedIn bio, press, etc.)
    language: str = "fr"


@dataclass
class RiskItem:
    level: str     # "élevé" | "moyen" | "faible"
    description: str


@dataclass
class FounderProfile:
    resume: str
    experience: str
    reputation: str
    signaux_positifs: list[str]
    signaux_negatifs: list[str]


@dataclass
class CompanyAnalysis:
    resume: str
    structure: str
    position_marche: str
    concurrents: list[str]
    risques: list[str]


@dataclass
class DeepDueOutput:
    due_id: str
    company_name: str
    founder_name: str
    generated_at: str
    language: str
    synthese_executive: str
    profil_fondateur: FounderProfile
    analyse_entreprise: CompanyAnalysis
    risques_identifies: list[RiskItem]
    recommandation_finale: str
    score_confiance: float      # 0–10
    raw_response: str


# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

def _build_system_prompt(language: str) -> str:
    if language == "fr":
        return """Tu es Deep Due, l'agent IA de Dealyze. Tu réalises des due diligences automatisées sur des entreprises et leurs fondateurs.

Ta mission : analyser toutes les informations disponibles et produire un rapport de due diligence structuré, objectif et actionnable pour un investisseur.

RÈGLES ABSOLUES :
— Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après
— Sois factuel et nuancé : signale l'absence d'information plutôt que d'inventer
— score_confiance : reflet de la qualité et quantité des données disponibles (pas de la qualité du deal)
— risques_identifies : au moins 2, avec niveau "élevé", "moyen" ou "faible"
— recommandation_finale : exactement une de ces valeurs : "Investir", "Ne pas investir", "Due diligence approfondie recommandée"

FORMAT DE SORTIE :
{
  "synthese_executive": "Résumé en 3-4 phrases pour un investisseur pressé",
  "profil_fondateur": {
    "resume": "Vue d'ensemble du fondateur",
    "experience": "Expériences professionnelles clés",
    "reputation": "Réputation publique et réseau",
    "signaux_positifs": ["signal 1", "signal 2"],
    "signaux_negatifs": ["signal 1", "signal 2"]
  },
  "analyse_entreprise": {
    "resume": "Vue d'ensemble de l'entreprise",
    "structure": "Structure légale et organisationnelle",
    "position_marche": "Position et dynamique concurrentielle",
    "concurrents": ["concurrent 1", "concurrent 2"],
    "risques": ["risque 1", "risque 2"]
  },
  "risques_identifies": [
    {"niveau": "élevé|moyen|faible", "description": "Description précise du risque"}
  ],
  "recommandation_finale": "Investir | Ne pas investir | Due diligence approfondie recommandée",
  "score_confiance": 7
}"""

    else:
        return """You are Deep Due, Dealyze's AI agent. You perform automated due diligence on companies and their founders.

Your mission: analyze all available information and produce a structured, objective, actionable due diligence report for an investor.

ABSOLUTE RULES:
— Reply ONLY with a valid JSON object, no text before or after
— Be factual and nuanced: flag missing information rather than inventing it
— score_confiance: reflects quality and quantity of available data (not deal quality)
— risques_identifies: at least 2, with level "high", "medium" or "low"
— recommandation_finale: exactly one of: "Invest", "Do not invest", "Further due diligence recommended"

OUTPUT FORMAT:
{
  "synthese_executive": "3-4 sentence summary for a busy investor",
  "profil_fondateur": {
    "resume": "Founder overview",
    "experience": "Key professional experiences",
    "reputation": "Public reputation and network",
    "signaux_positifs": ["signal 1", "signal 2"],
    "signaux_negatifs": ["signal 1", "signal 2"]
  },
  "analyse_entreprise": {
    "resume": "Company overview",
    "structure": "Legal and organizational structure",
    "position_marche": "Market position and competitive dynamics",
    "concurrents": ["competitor 1", "competitor 2"],
    "risques": ["risk 1", "risk 2"]
  },
  "risques_identifies": [
    {"niveau": "high|medium|low", "description": "Precise risk description"}
  ],
  "recommandation_finale": "Invest | Do not invest | Further due diligence recommended",
  "score_confiance": 7
}"""


def _build_user_prompt(inputs: DeepDueInput) -> str:
    founder_line = f"FONDATEUR : {inputs.founder_name}" if inputs.founder_name else "FONDATEUR : Non renseigné"
    context_block = (
        f"\nINFORMATIONS DISPONIBLES :\n{inputs.context}"
        if inputs.context
        else "\nINFORMATIONS DISPONIBLES : Uniquement les informations publiques connues sur cette entreprise."
    )

    if inputs.language == "fr":
        return (
            f"Réalise la due diligence pour :\n\n"
            f"ENTREPRISE : {inputs.company_name}\n"
            f"{founder_line}"
            f"{context_block}\n\n"
            f"Génère maintenant le rapport JSON complet."
        )
    else:
        return (
            f"Perform due diligence for:\n\n"
            f"COMPANY: {inputs.company_name}\n"
            f"FOUNDER: {inputs.founder_name or 'Not provided'}"
            f"{context_block}\n\n"
            f"Now generate the complete JSON report."
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
    logger.warning("[DeepDue] JSON parsing failed")
    return {}


def _parse_founder(d: dict) -> FounderProfile:
    return FounderProfile(
        resume=d.get("resume", ""),
        experience=d.get("experience", ""),
        reputation=d.get("reputation", ""),
        signaux_positifs=d.get("signaux_positifs", []),
        signaux_negatifs=d.get("signaux_negatifs", []),
    )


def _parse_company(d: dict) -> CompanyAnalysis:
    return CompanyAnalysis(
        resume=d.get("resume", ""),
        structure=d.get("structure", ""),
        position_marche=d.get("position_marche", ""),
        concurrents=d.get("concurrents", []),
        risques=d.get("risques", []),
    )


def _parse_risks(items: list) -> list[RiskItem]:
    return [
        RiskItem(level=r.get("niveau", "moyen"), description=r.get("description", ""))
        for r in items
        if isinstance(r, dict)
    ]


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #

class DeepDueAgent:
    """
    Automated due diligence on a company and its founder.
    Works with optional context provided by the user (copy-paste from LinkedIn,
    Crunchbase, press, etc.) — web scraping integration can be plugged in later.
    """

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    def analyze(self, inputs: DeepDueInput) -> DeepDueOutput:
        due_id = f"DD2-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        logger.info(
            "[DeepDue] START | id=%s | company=%s | founder=%s | context_chars=%d | lang=%s",
            due_id, inputs.company_name, inputs.founder_name or "N/A",
            len(inputs.context), inputs.language,
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _build_system_prompt(inputs.language)},
                {"role": "user",   "content": _build_user_prompt(inputs)},
            ],
            temperature=0.3,   # low = more factual, less creative
            max_tokens=2048,
        )

        raw    = response.choices[0].message.content
        parsed = _parse_json(raw)

        score  = float(parsed.get("score_confiance", 5))
        reco   = parsed.get("recommandation_finale", "")

        logger.info(
            "[DeepDue] DONE  | id=%s | score_confiance=%.1f | recommandation=%s | tokens=%s",
            due_id, score, reco,
            response.usage.total_tokens if response.usage else "N/A",
        )

        return DeepDueOutput(
            due_id=due_id,
            company_name=inputs.company_name,
            founder_name=inputs.founder_name,
            generated_at=datetime.now().isoformat(),
            language=inputs.language,
            synthese_executive=parsed.get("synthese_executive", ""),
            profil_fondateur=_parse_founder(parsed.get("profil_fondateur", {})),
            analyse_entreprise=_parse_company(parsed.get("analyse_entreprise", {})),
            risques_identifies=_parse_risks(parsed.get("risques_identifies", [])),
            recommandation_finale=reco,
            score_confiance=score,
            raw_response=raw,
        )
