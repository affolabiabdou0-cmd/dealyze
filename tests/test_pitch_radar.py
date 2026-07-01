"""
Test de l'agent Pitch Radar.
Lance avec : python tests/test_pitch_radar.py
"""
import logging
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from agents.pitch_radar import PitchRadarAgent, PitchRadarInput

_agent = PitchRadarAgent()

# Pitch deck fictif mais réaliste
SAMPLE_DECK_FR = """
DEALFLOW AI — Pitch Deck — Série A — 2 M€

ÉQUIPE
- Sophie Laurent, CEO — 10 ans en fintech, ex-VP Product chez Lydia, MBA HEC
- Marc Dupont, CTO — ex-ingénieur senior chez Stripe, 8 ans d'expérience
- Aline Berger, CMO — ex-directrice marketing chez Alan, spécialiste growth B2B

PROBLÈME
Les équipes financières des PME passent 12h/semaine à réconcilier manuellement leurs données comptables
entre 4 à 7 outils différents (ERP, banques, comptabilité, CRM). Cela représente un coût de 47 000€/an/PME.

SOLUTION
DealFlow AI unifie et réconcilie automatiquement toutes les données financières en temps réel grâce à l'IA.
Temps de réconciliation : 12h → 15 minutes. ROI client moyen : x8 en 6 mois.

MARCHÉ
- TAM : 180 milliards € (marché mondial SaaS fintech PME)
- SAM : 12 milliards € (Europe, PME 10-200 salariés)
- SOM : 120 millions € (France, Belgique, Suisse — objectif an 3)

TRACTION
- 47 clients payants (MRR : 38 000€, croissance +22% MoM)
- Churn mensuel : 1.2%
- NPS : 72
- Pipeline qualifié : 280 k€ ARR
- Partenariats signés : Pennylane, Qonto

MODÈLE ÉCONOMIQUE
SaaS mensuel : 299€/mois (PME), 799€/mois (ETI).
Marge brute : 78%. LTV moyenne : 18 400€. CAC : 1 200€. LTV/CAC : 15.

CONCURRENCE
- Pennylane : comptabilité mais pas de réconciliation IA
- Agicap : trésorerie mais pas de réconciliation multi-sources
- Spendesk : dépenses uniquement
Différenciation : seul outil qui connecte toutes les sources et réconcilie avec l'IA.

LEVÉE DE FONDS
Montant : 2 000 000€ en Série A
Utilisation : 60% R&D (3 ingénieurs), 30% commercial (2 AE), 10% infra
Valorisation pre-money : 8 000 000€
"""

SAMPLE_DECK_EN = """
NEXCART — Series A Pitch — $3M raise

TEAM
- James Park, CEO — 2nd time founder, previously sold SaaS to Oracle for $12M
- Priya Mehta, CTO — MIT graduate, 6 years at Amazon AWS, built systems at scale
- No dedicated CMO or sales lead yet

PROBLEM
E-commerce brands lose 23% of potential revenue to cart abandonment.
Current tools (Klaviyo, Mailchimp) send generic recovery emails with 8% average open rate.

SOLUTION
NexCart uses AI to personalize recovery sequences in real time based on browsing behavior,
past purchases, and social signals. Our emails average 34% open rate and 18% recovery rate.

MARKET
- TAM: $50B (global e-commerce SaaS)
- SAM: $4B (mid-market Shopify/WooCommerce brands)
- SOM: $200M (US, UK, Canada — Year 3)

TRACTION
- 12 paying customers (MRR: $8,400, +15% MoM)
- Average contract: $700/month
- Pipeline: 3 enterprise deals ($180k ARR combined)

BUSINESS MODEL
SaaS: $299–$999/month per store.
Gross margin: 71%. LTV: $12,600. CAC: $2,100.

COMPETITION
- Klaviyo: generic automation, no AI personalization
- CartStack: rule-based, not AI-native
Differentiation: only AI-native cart recovery with real-time behavioral signals.

FUNDRAISE
Seeking $3M Seed/Series A
Use of funds: 50% engineering (4 hires), 35% sales & marketing, 15% ops
Pre-money valuation: $9M
"""


def run_test(label: str, inputs: PitchRadarInput):
    print(f"\n{'='*65}")
    print(f"TEST : {label}")
    print(f"{'='*65}")
    print("Analyse en cours...", flush=True)

    t0 = time.time()
    r = _agent.analyze(inputs)
    elapsed = time.time() - t0

    print(f"ID             : {r.radar_id}  ({elapsed:.1f}s)")
    print(f"Score global   : {r.score_global}/10")
    print(f"Recommandation : {r.recommandation}")
    print(f"\nScores détaillés :")
    for s in r.scores:
        bar = "█" * int(s.score) + "░" * (10 - int(s.score))
        print(f"  {s.label:<22} {bar} {s.score:4.1f}/10  {s.note[:60]}")
    print(f"\nPoints forts :")
    for pf in r.points_forts:
        print(f"  ✓ {pf}")
    print(f"\nPoints d'alerte :")
    for pa in r.points_alerte:
        print(f"  ⚠ {pa}")
    print(f"\nQuestions à poser au fondateur :")
    for i, q in enumerate(r.questions_suggerees, 1):
        print(f"  {i}. {q}")


if __name__ == "__main__":
    run_test(
        "Pitch FR — DealFlow AI (Série A, fintech)",
        PitchRadarInput(
            deck_text=SAMPLE_DECK_FR,
            startup_name="DealFlow AI",
            language="fr",
        ),
    )

    run_test(
        "Pitch EN — NexCart (Series A, e-commerce SaaS)",
        PitchRadarInput(
            deck_text=SAMPLE_DECK_EN,
            startup_name="NexCart",
            language="en",
        ),
    )
