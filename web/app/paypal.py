"""Client PayPal REST minimal (stdlib urllib, même approche que gemini_engine.py).

Utilisé pour : créer le produit/plan/webhook (scripts/setup_paypal.py), vérifier un abonnement
après approbation côté client, résilier un abonnement, et vérifier la signature des webhooks.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.config import PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_MODE

API_BASE = (
    "https://api-m.paypal.com" if PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"
)

_token_cache: dict = {"value": None, "expires_at": 0.0}


class PayPalError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None, auth_token: str | None = None) -> dict:
    url = f"{API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PayPalError(f"PayPal API error {exc.code} on {method} {path}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise PayPalError(f"Connexion à PayPal impossible : {exc.reason}") from exc


def get_access_token() -> str:
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"]

    import base64

    credentials = base64.b64encode(f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode()).decode()
    url = f"{API_BASE}/v1/oauth2/token"
    req = urllib.request.Request(
        url,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PayPalError(f"Authentification PayPal refusée : {detail[:300]}") from exc

    token = payload["access_token"]
    _token_cache["value"] = token
    _token_cache["expires_at"] = now + payload.get("expires_in", 3600) - 60
    return token


def _authed_request(method: str, path: str, body: dict | None = None) -> dict:
    return _request(method, path, body, auth_token=get_access_token())


# --- Produit / Plan (setup unique, voir scripts/setup_paypal.py) ------------

def create_product(name: str, description: str) -> dict:
    return _authed_request("POST", "/v1/catalogs/products", {
        "name": name,
        "description": description,
        "type": "SERVICE",
        "category": "SOFTWARE",
    })


def create_plan(product_id: str, name: str, intro_price: str, regular_price: str, currency: str = "EUR") -> dict:
    """Plan à 2 paliers : `intro_price`/mois pendant 6 mois, puis `regular_price`/mois à vie."""
    return _authed_request("POST", "/v1/billing/plans", {
        "product_id": product_id,
        "name": name,
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 6,
                "pricing_scheme": {"fixed_price": {"value": intro_price, "currency_code": currency}},
            },
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": regular_price, "currency_code": currency}},
            },
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "payment_failure_threshold": 2,
        },
    })


def create_webhook(url: str, event_types: list[str]) -> dict:
    return _authed_request("POST", "/v1/notifications/webhooks", {
        "url": url,
        "event_types": [{"name": e} for e in event_types],
    })


# --- Abonnements --------------------------------------------------------

def get_subscription(subscription_id: str) -> dict:
    return _authed_request("GET", f"/v1/billing/subscriptions/{subscription_id}")


def cancel_subscription(subscription_id: str, reason: str = "Résilié par l'utilisateur") -> None:
    _authed_request(
        "POST", f"/v1/billing/subscriptions/{subscription_id}/cancel", {"reason": reason}
    )


def verify_webhook_signature(headers: dict, body: str, webhook_id: str) -> bool:
    payload = {
        "auth_algo": headers.get("paypal-auth-algo"),
        "cert_url": headers.get("paypal-cert-url"),
        "transmission_id": headers.get("paypal-transmission-id"),
        "transmission_sig": headers.get("paypal-transmission-sig"),
        "transmission_time": headers.get("paypal-transmission-time"),
        "webhook_id": webhook_id,
        "webhook_event": json.loads(body),
    }
    result = _authed_request("POST", "/v1/notifications/verify-webhook-signature", payload)
    return result.get("verification_status") == "SUCCESS"
