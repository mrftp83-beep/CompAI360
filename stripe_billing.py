"""Optional Stripe Billing integration.

Stripe is the payment system of record. This module never stores payment
credentials. Set STRIPE_SECRET_KEY and plan price IDs in the environment.
"""
import os, secrets

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None


def _client():
    if stripe is None:
        raise RuntimeError("Stripe SDK is not installed")
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return stripe.StripeClient(key)


def price_for_plan(plan: str) -> str:
    key = f"STRIPE_PRICE_{plan.upper()}"
    value = os.getenv(key)
    if not value:
        raise ValueError(f"No Stripe price configured for plan {plan}")
    return value


def create_checkout(email: str, plan: str, success_url: str, cancel_url: str):
    client = _client()
    suffix = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8))
    return client.v1.checkout.sessions.create({
        "mode": "subscription",
        "line_items": [{"price": price_for_plan(plan), "quantity": 1}],
        "customer_email": email,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "integration_identifier": f"cai_checkout_{suffix}",
    })


def construct_event(payload: bytes, signature: str):
    if stripe is None:
        raise RuntimeError("Stripe SDK is not installed")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    return stripe.Webhook.construct_event(payload, signature, secret)
