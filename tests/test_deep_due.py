"""
Test de l'agent Deep Due.
Lance avec : python tests/test_deep_due.py
"""
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from agents.deep_due import DeepDueAgent, DeepDueInput

_agent = DeepDueAgent()

CONTEXT_AIRBNB = """
Airbnb a été fondée en 2008 par Brian Chesky, Joe Gebbia et Nathan Blecharczyk à San Francisco.
Brian Chesky est diplômé du Rhode Island School of Design. Avant Airbnb, il travaillait comme designer
industriel. Joe Gebbia, co-fondateur et designer, est connu pour son rôle crucial dans le lancement
initial de l'idée via des matelas gonflables pendant une conférence à SF.
L'entreprise est entrée en bourse en décembre 2020 (IPO NASDAQ : ABNB) à une valorisation de 47 milliards $.
Airbnb opère dans 220 pays, 100 000 villes, avec 4 millions d'hôtes et 900 millions de voyageurs cumulés.
Revenus 2023 : 9,9 milliards $. Bénéfice net 2023 : 4,8 milliards $ (premier exercice pleinement rentable).
Risques identifiés : réglementation locale hostile dans plusieurs grandes villes (Paris, New York, Amsterdam),
concurrence Vrbo/Booking, dépendance aux voyages internationaux (sensible aux crises sanitaires/géopolitiques).
"""

CONTEXT_UNKNOWN = ""  # aucun contexte — l'agent doit signaler le manque d'info


def run_test(label: str, inputs: DeepDueInput):
    print(f"\n{'='*65}")
    print(f"TEST : {label}")
    print(f"{'='*65}")
    print("Analyse en cours...", flush=True)

    t0 = time.time()
    r = _agent.analyze(inputs)
    elapsed = time.time() - t0

    print(f"ID Due         : {r.due_id}  ({elapsed:.1f}s)")
    print(f"Score confiance: {r.score_confiance}/10")
    print(f"Recommandation : {r.recommandation_finale}")

    print(f"\nSYNTHÈSE EXECUTIVE :\n{r.synthese_executive}")

    print(f"\nPROFIL FONDATEUR :")
    print(f"  Résumé    : {r.profil_fondateur.resume}")
    print(f"  Expérience: {r.profil_fondateur.experience}")
    print(f"  ✓ Positifs: {r.profil_fondateur.signaux_positifs}")
    print(f"  ⚠ Négatifs: {r.profil_fondateur.signaux_negatifs}")

    print(f"\nANALYSE ENTREPRISE :")
    print(f"  Position  : {r.analyse_entreprise.position_marche}")
    print(f"  Concurrents: {r.analyse_entreprise.concurrents}")

    print(f"\nRISQUES IDENTIFIÉS :")
    for risk in r.risques_identifies:
        icon = {"élevé": "🔴", "moyen": "🟡", "faible": "🟢", "high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk.level, "⚪")
        print(f"  {icon} [{risk.level.upper()}] {risk.description}")


if __name__ == "__main__":
    # Cas 1 — entreprise connue avec contexte riche
    run_test(
        "Airbnb — entreprise connue + contexte fourni (FR)",
        DeepDueInput(
            company_name="Airbnb",
            founder_name="Brian Chesky",
            context=CONTEXT_AIRBNB,
            language="fr",
        ),
    )

    # Cas 2 — startup inconnue sans contexte (test de robustesse)
    run_test(
        "Startup inconnue — sans contexte (test robustesse)",
        DeepDueInput(
            company_name="NovaTech Solutions",
            founder_name="Ahmed Bouali",
            context=CONTEXT_UNKNOWN,
            language="fr",
        ),
    )

    # Cas 3 — English
    run_test(
        "OpenAI — English, known company",
        DeepDueInput(
            company_name="OpenAI",
            founder_name="Sam Altman",
            context="",
            language="en",
        ),
    )
