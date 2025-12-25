#!/usr/bin/env python
import os
import sys
import stripe

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    print("[ERR] STRIPE_SECRET_KEY environment variable not set")
    sys.exit(1)

stripe.api_key = STRIPE_SECRET_KEY

PLANS = {
    "starter": {
        "amount": 499,
        "currency": "eur",
        "product_name": "eBay Agent Cockpit - Starter (25 alerts, SMS)",
        "interval": "month",
    },
    "basic": {
        "amount": 999,
        "currency": "eur",
        "product_name": "eBay Agent Cockpit - Basic (100 alerts, PDF Reports)",
        "interval": "month",
    },
    "pro": {
        "amount": 1999,
        "currency": "eur",
        "product_name": "eBay Agent Cockpit - Pro (500 alerts, API Access)",
        "interval": "month",
    },
    "enterprise": {
        "amount": 4999,
        "currency": "eur",
        "product_name": "eBay Agent Cockpit - Enterprise (5000 alerts)",
        "interval": "month",
    },
    "custom": {
        "amount": 9900,
        "currency": "eur",
        "product_name": "eBay Agent Cockpit - Custom (White-Label, Unlimited)",
        "interval": "month",
    }
}

price_ids = {}

print("=" * 70)
print("Creating Stripe Prices for eBay Agent Cockpit")
print("=" * 70)

for plan_name, config in PLANS.items():
    try:
        print(f"\n[...] Creating {plan_name.upper()}...", end=" ")
        
        product = stripe.Product.create(
            name=config["product_name"],
            type="service",
            metadata={"plan": plan_name}
        )
        print(f"\n    Product: {product.id}")
        
        price = stripe.Price.create(
            product=product.id,
            unit_amount=config["amount"],
            currency=config["currency"],
            recurring={
                "interval": config["interval"],
                "interval_count": 1,
                "usage_type": "licensed"
            },
            metadata={"plan": plan_name},
            billing_scheme="per_unit"
        )
        
        price_ids[plan_name] = price.id
        print(f"    Price ID: {price.id} [OK]")
        
    except stripe.error.StripeError as e:
        print(f"\n[ERR] {plan_name}: {e.user_message}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERR] {plan_name}: {str(e)}")
        sys.exit(1)

print("\n" + "=" * 70)
print("SUCCESS! Add these to your .env file:")
print("=" * 70)

for plan_name, price_id in price_ids.items():
    env_var = f"STRIPE_PRICE_{plan_name.upper()}"
    print(f"{env_var}={price_id}")

with open(".env.stripe_prices", "w") as f:
    for plan_name, price_id in price_ids.items():
        env_var = f"STRIPE_PRICE_{plan_name.upper()}"
        f.write(f"{env_var}={price_id}\n")

print("\n[OK] Saved to .env.stripe_prices")
print("\nNext: Copy the Price IDs above to your .env file and restart the app")
