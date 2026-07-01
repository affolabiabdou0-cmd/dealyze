import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from agents.gemini_client import get_gemini_model

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scoring grid                                                                 #
# --------------------------------------------------------------------------- #

# Standard VC criteria with weights (must sum to 1.0)
DEFAULT_CRITERIA = {
    "equipe":              {"label": "Équipe",              "weight": 0.20},
    "marche":              {"label": "Marché",              "weight": 0.15},
    "probleme":            {"label": "Problème",            "weight": 0.10},
    "solution":            {"label": "Solution",            "weight": 0.15},
    "traction":            {"label": "Traction",            "weight": 0.20},
    "modele_economique":   {"label": "Modèle économique",   "weight": 0.10},
    "concurrence":         {"label": "Concurrence",         "weight": 0.05},
    "demande_financement": {"label": "Demande financement", "weight": 0.05},
}


# --------------------------------------------------------------------------- #
# Data models                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class PitchRadarInput:
    deck_text: str                          # extracted text from pitch deck
    startup_name: str = "Startup"
    user_criteria: dict = field(default_factory=dict)   # override weights
    language: str = "fr"


@dataclass
class CriterionScore:
    key: str
    label: str
    score: float     # 0–10
    weight: float
    note: str


@dataclass
class PitchRadarOutput:
    radar_id: str
    startup_name: str
    generated_at: str
    language: str
    scores: list[CriterionScore]
    score_global: float
    points_forts: list[str]
    points_alerte: list[str]
    questions_suggerees: list[str]
    recommandation: str
    raw_response: str


# --------------------------------------------------------------------------- #
# Weighted score                                                               #
# --------------------------------------------------------------------------- #

def _weighted_score(scores_dict: dict, criteria: dict) -> float:
    total = 0.0
    for key, meta in criteria.items():
        s = scores_dict.get(key, {}).get("score", 5)
        total += float(s) * meta["weight"]
    return round(total, 1)


# --------------------------------------------------------------------------- #
# Prompts                                                                      #
# --------------------------------------------------------------------------- #

def _build_criteria_block(criteria: dict, language: str) -> str:
    lines = []
    for key, meta in criteria.items():
        pct = int(meta["weight"] * 100)
        lines.append(f'  "{key}": {{"score": X, "note": "..."}}  // {meta["label"]} — poids {pct}%')
    return "\n".join(lines)


def _build_system_prompt(criteria: dict, language: str) -> str:
    criteria_block = _build_criteria_block(criteria, language)

    if language == "fr":
        return f"""Tu es Pitch Radar, l'agent IA de Dealyze. Tu analyses des pitch decks et produis des rapports d'investissement structurés.

GRILLE DE NOTATION (scores de 0 à 10) :
{criteria_block}

RÈGLES ABSOLUES :
— Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après
— Chaque score doit être justifié par une note courte (max 40 mots)
— points_forts : exactement 3 éléments, spécifiques au deck analysé
— points_alerte : exactement 3 éléments, spécifiques au deck analysé
— questions_suggerees : exactement 5 questions à poser au fondateur
— recommandation : exactement une de ces trois valeurs : "À investir", "À surveiller", "À passer"

FORMAT DE SORTIE :
{{
  "scores": {{
{criteria_block}
  }},
  "points_forts": ["...", "...", "..."],
  "points_alerte": ["...", "...", "..."],
  "questions_suggerees": ["...", "...", "...", "...", "..."],
  "recommandation": "À investir | À surveiller | À passer"
}}"""

    else:
        return f"""You are Pitch Radar, Dealyze's AI agent. You analyze pitch decks and produce structured investment reports.

SCORING GRID (scores 0 to 10):
{criteria_block}

ABSOLUTE RULES:
— Reply ONLY with a valid JSON object, no text before or after
— Each score must be justified by a short note (max 40 words)
— points_forts: exactly 3 items, specific to this deck
— points_alerte: exactly 3 items, specific to this deck
— questions_suggerees: exactly 5 questions to ask the founder
— recommandation: exactly one of: "To invest", "To watch", "To pass"

OUTPUT FORMAT:
{{
  "scores": {{
{criteria_block}
  }},
  "points_forts": ["...", "...", "..."],
  "points_alerte": ["...", "...", "..."],
  "questions_suggerees": ["...", "...", "...", "...", "..."],
  "recommandation": "To invest | To watch | To pass"
}}"""


def _build_user_prompt(inputs: PitchRadarInput) -> str:
    if inputs.language == "fr":
        return (
            f"Analyse ce pitch deck pour la startup : {inputs.startup_name}\n\n"
            f"--- CONTENU DU PITCH DECK ---\n"
            f"{inputs.deck_text}\n"
            f"--- FIN DU PITCH DECK ---\n\n"
            f"Génère maintenant le rapport JSON complet."
        )
    else:
        return (
            f"Analyze this pitch deck for startup: {inputs.startup_name}\n\n"
            f"--- PITCH DECK CONTENT ---\n"
            f"{inputs.deck_text}\n"
            f"--- END OF PITCH DECK ---\n\n"
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
    logger.warning("[PitchRadar] JSON parsing failed")
    return {}


def _build_criterion_scores(parsed_scores: dict, criteria: dict) -> list[CriterionScore]:
    result = []
    for key, meta in criteria.items():
        raw = parsed_scores.get(key, {})
        result.append(CriterionScore(
            key=key,
            label=meta["label"],
            score=float(raw.get("score", 5)),
            weight=meta["weight"],
            note=raw.get("note", ""),
        ))
    return result


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #

class PitchRadarAgent:
    """
    Analyzes a pitch deck text and returns a structured VC-style scoring report.
    Accepts either raw text or PDF bytes (via utils.pdf_reader).
    """

    def __init__(self):
        self.model = get_gemini_model("gemini-1.5-flash")

    def analyze(self, inputs: PitchRadarInput) -> PitchRadarOutput:
        criteria = dict(DEFAULT_CRITERIA)
        if inputs.user_criteria:
            for key, val in inputs.user_criteria.items():
                if key in criteria:
                    criteria[key].update(val)

        radar_id = f"PR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        logger.info(
            "[PitchRadar] START | id=%s | startup=%s | lang=%s | deck_chars=%d",
            radar_id, inputs.startup_name, inputs.language, len(inputs.deck_text),
        )

        prompt = _build_system_prompt(criteria, inputs.language) + "\n\n" + _build_user_prompt(inputs)
        response = self.model.generate_content(prompt)
        raw    = response.text
        parsed = _parse_json(raw)

        criterion_scores = _build_criterion_scores(parsed.get("scores", {}), criteria)
        score_global = _weighted_score(parsed.get("scores", {}), criteria)

        logger.info(
            "[PitchRadar] DONE | id=%s | score=%.1f/10 | recommandation=%s",
            radar_id, score_global, parsed.get("recommandation", "N/A"),
        )

        return PitchRadarOutput(
            radar_id=radar_id,
            startup_name=inputs.startup_name,
            generated_at=datetime.now().isoformat(),
            language=inputs.language,
            scores=criterion_scores,
            score_global=score_global,
            points_forts=parsed.get("points_forts", []),
            points_alerte=parsed.get("points_alerte", []),
            questions_suggerees=parsed.get("questions_suggerees", []),
            recommandation=parsed.get("recommandation", ""),
            raw_response=raw,
        )
