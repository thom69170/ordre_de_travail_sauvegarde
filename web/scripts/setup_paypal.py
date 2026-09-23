"""Crée le produit, le plan tarifaire (1€/mois x6 puis 2€/mois) et le webhook PayPal.

À exécuter UNE SEULE FOIS par environnement (sandbox, puis live) :

    docker exec ot-app-1 python -m scripts.setup_paypal https://ot.notivo.fr/billing/webhook

Affiche le PLAN_ID et le WEBHOOK_ID à copier dans .env (PAYPAL_PLAN_ID / PAYPAL_WEBHOOK_ID).
"""
from __future__ import annotations

import sys

from app import paypal
from app.config import PAYPAL_MODE

EVENT_TYPES = [
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.EXPIRED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "PAYMENT.SALE.COMPLETED",
    "PAYMENT.SALE.DENIED",
]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.setup_paypal <webhook_url>")
        sys.exit(1)
    webhook_url = sys.argv[1]

    print(f"Mode PayPal : {PAYPAL_MODE}")

    product = paypal.create_product(
        "Ordre de travail - Abonnement", "Accès à l'application Ordre de travail"
    )
    product_id = product["id"]
    print(f"Produit créé : {product_id}")

    plan = paypal.create_plan(
        product_id,
        "Abonnement mensuel Ordre de travail",
        intro_price="1.00",
        regular_price="2.00",
    )
    plan_id = plan["id"]
    print(f"Plan créé : {plan_id}")

    webhook = paypal.create_webhook(webhook_url, EVENT_TYPES)
    webhook_id = webhook["id"]
    print(f"Webhook créé : {webhook_id}")

    print()
    print("À coller dans .env :")
    print(f"PAYPAL_PLAN_ID={plan_id}")
    print(f"PAYPAL_WEBHOOK_ID={webhook_id}")


if __name__ == "__main__":
    main()
