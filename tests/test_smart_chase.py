"""
Test de l'agent Smart Chase — 4 scénarios couvrant les 4 niveaux d'escalade.
Lance avec : python tests/test_smart_chase.py
"""
import logging
import sys
import os
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

from agents.smart_chase import SmartChaseAgent, SmartChaseInput, InvoiceData

_agent = SmartChaseAgent()  # une seule instance pour tous les tests


def due(days_ago: int) -> str:
    """Helper: date d'échéance qui était il y a N jours."""
    return (date.today() - timedelta(days=days_ago)).isoformat()


def run_test(label: str, inputs: SmartChaseInput):
    print(f"\n{'='*65}")
    print(f"TEST : {label}")
    print(f"{'='*65}")
    print("Génération en cours...", flush=True)

    t0 = time.time()
    r = _agent.generate(inputs)
    elapsed = time.time() - t0

    print(f"ID Chase        : {r.chase_id}  ({elapsed:.1f}s)")
    print(f"Profil client   : {r.client_profile}")
    print(f"Jours de retard : {r.days_overdue}")
    print(f"Niveau escalade : {r.escalation_level}/4")
    print(f"Ton appliqué    : {r.tone}")
    print(f"Prochaine action: {r.next_action_date}")
    print(f"\nOBJET  : {r.email_subject}")
    print(f"\nCORPS  :\n{r.email_body}")


if __name__ == "__main__":

    # Niveau 1 — bon payeur, 5 jours de retard, premier rappel
    run_test(
        "Niveau 1 — Bon payeur, retard 5 jours, 0 relance",
        SmartChaseInput(
            invoice=InvoiceData(
                invoice_id="FAC-2026-041",
                client_name="Lumière & Co",
                amount=4200.0,
                currency="EUR",
                due_date=due(5),
                issue_date=due(35),
                description="Mission conseil stratégique — Mai 2026",
                previous_reminders=0,
                payment_history="bon_payeur",
            ),
            company_name="Agence Nova",
            chase_style="bienveillant",
            language="fr",
        ),
    )

    # Niveau 2 — nouveau client, 15 jours, 1 relance déjà envoyée
    run_test(
        "Niveau 2 — Nouveau client, retard 15 jours, 1 relance",
        SmartChaseInput(
            invoice=InvoiceData(
                invoice_id="FAC-2026-037",
                client_name="StartupXYZ",
                amount=9800.0,
                currency="EUR",
                due_date=due(15),
                issue_date=due(45),
                description="Développement MVP — Phase 1",
                previous_reminders=1,
                payment_history="nouveau_client",
            ),
            company_name="DevStudio Paris",
            chase_style="professionnel",
            language="fr",
        ),
    )

    # Niveau 3 — mauvais payeur, 32 jours, 2 relances
    run_test(
        "Niveau 3 — Mauvais payeur, retard 32 jours, 2 relances",
        SmartChaseInput(
            invoice=InvoiceData(
                invoice_id="FAC-2026-028",
                client_name="Batiment Pro SARL",
                amount=12500.0,
                currency="EUR",
                due_date=due(32),
                issue_date=due(62),
                description="Audit sécurité site industriel",
                previous_reminders=2,
                payment_history="mauvais_payeur",
            ),
            company_name="SafeConsult",
            chase_style="ferme",
            language="fr",
        ),
    )

    # Niveau 4 — English, 50 days overdue, 3 reminders
    run_test(
        "Niveau 4 — EN, chronic bad payer, 50 days overdue, 3 reminders",
        SmartChaseInput(
            invoice=InvoiceData(
                invoice_id="INV-2026-019",
                client_name="Greenfield Corp",
                amount=18750.0,
                currency="USD",
                due_date=due(50),
                issue_date=due(80),
                description="Marketing strategy Q1 2026",
                previous_reminders=3,
                payment_history="mauvais_payeur",
            ),
            company_name="BoldAgency Inc.",
            chase_style="ferme",
            language="en",
        ),
    )
