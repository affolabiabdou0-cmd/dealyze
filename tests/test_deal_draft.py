"""
Test rapide de l'agent Deal Draft.
Lance avec : python tests/test_deal_draft.py
"""
import logging
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

from agents.deal_draft import DealDraftAgent, DealDraftInput

_agent = DealDraftAgent()  # une seule instance pour tous les tests


def run_test(label: str, inputs: DealDraftInput):
    print(f"\n{'='*60}")
    print(f"TEST : {label}")
    print(f"{'='*60}")
    print("Génération en cours...", flush=True)

    t0 = time.time()
    result = _agent.generate(inputs)
    elapsed = time.time() - t0

    print(f"ID        : {result.quote_id}  ({elapsed:.1f}s)")
    print(f"Ton       : {result.tone}")
    print(f"Généré le : {result.generated_at}")
    print(f"\n--- CONTENU DU DEVIS ---")
    print(json.dumps(result.content, ensure_ascii=False, indent=2))

    print(f"ID        : {result.quote_id}")
    print(f"Ton       : {result.tone}")
    print(f"Généré le : {result.generated_at}")
    print(f"\n--- CONTENU DU DEVIS ---")
    print(json.dumps(result.content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # Cas 1 — PME agence web (ton dynamique)
    run_test(
        "PME agence web — devis création site e-commerce",
        DealDraftInput(
            client_name="TechStyle Paris",
            sector="Agence web / e-commerce",
            need="Création d'un site e-commerce pour vendre des accessoires de mode en ligne",
            budget="8 000 €",
            timeline="6 semaines",
            language="fr",
        ),
    )

    # Cas 2 — Cabinet juridique (ton formel)
    run_test(
        "Cabinet juridique — devis audit contractuel",
        DealDraftInput(
            client_name="Cabinet Moreau & Associés",
            sector="Cabinet juridique",
            need="Audit et mise à jour des contrats fournisseurs suite à une nouvelle réglementation",
            budget="5 000 €",
            timeline="3 semaines",
            language="fr",
        ),
    )

    # Cas 3 — English / startup (dynamic tone)
    run_test(
        "English — SaaS startup, growth marketing",
        DealDraftInput(
            client_name="Nexflow Inc.",
            sector="SaaS / tech startup",
            need="Full growth marketing strategy + LinkedIn content for Q3 launch",
            budget="$12,000",
            timeline="8 weeks",
            language="en",
        ),
    )
