"""
💎 PREMIUM FEATURES SYSTEM
Monetarisierung mit Freemium-Modell
"""
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum

log = logging.getLogger(__name__)


class PlanType(Enum):
    """Verfügbare Pläne"""
    FREE = 'free'
    BASIC = 'basic'
    PRO = 'pro'
    ULTIMATE = 'ultimate'


class FeatureLimits:
    """Feature-Limits pro Plan"""

    LIMITS = {
        'free': {
            'alerts': 3,
            'check_interval': 5,  # Minuten
            'marketplaces': ['ebay', 'kleinanzeigen'],
            'results_per_search': 20,
            'price_history': False,
            'ai_analysis': False,
            'whatsapp': False,
            'priority_alerts': False,
            'saved_searches': 5,
            'watchlist_items': 10,
            'export_data': False,
            'api_access': False,
            'support': 'community'
        },
        'basic': {
            'alerts': 10,
            'check_interval': 3,
            'marketplaces': ['ebay', 'kleinanzeigen', 'quoka'],
            'results_per_search': 50,
            'price_history': True,
            'ai_analysis': False,
            'whatsapp': True,
            'priority_alerts': False,
            'saved_searches': 20,
            'watchlist_items': 50,
            'export_data': True,
            'api_access': False,
            'support': 'email',
            'price_monthly': 4.99,
            'price_yearly': 49.99
        },
        'pro': {
            'alerts': 50,
            'check_interval': 1,  # Jede Minute!
            'marketplaces': ['ebay', 'kleinanzeigen', 'quoka', 'shpock', 'marktde'],
            'results_per_search': 100,
            'price_history': True,
            'ai_analysis': True,
            'whatsapp': True,
            'priority_alerts': True,
            'saved_searches': 100,
            'watchlist_items': 200,
            'export_data': True,
            'api_access': True,
            'support': 'priority',
            'price_monthly': 9.99,
            'price_yearly': 99.99
        },
        'ultimate': {
            'alerts': 'unlimited',
            'check_interval': 1,
            'marketplaces': 'all',
            'results_per_search': 'unlimited',
            'price_history': True,
            'ai_analysis': True,
            'whatsapp': True,
            'priority_alerts': True,
            'saved_searches': 'unlimited',
            'watchlist_items': 'unlimited',
            'export_data': True,
            'api_access': True,
            'custom_alerts': True,
            'dedicated_support': True,
            'white_label': True,
            'support': '24/7',
            'price_monthly': 19.99,
            'price_yearly': 199.99
        }
    }

    @classmethod
    def get_limits(cls, plan: str) -> Dict:
        """Holt Limits für einen Plan"""
        return cls.LIMITS.get(plan, cls.LIMITS['free'])

    @classmethod
    def check_feature(cls, plan: str, feature: str) -> bool:
        """Prüft ob Feature verfügbar"""
        limits = cls.get_limits(plan)
        return limits.get(feature, False)


def check_feature_access(user: Dict, feature: str) -> Dict:
    """
    💎 Prüft ob User Zugriff auf Feature hat

    Args:
        user: User-Dict mit plan_type
        feature: Feature-Name

    Returns:
        Dict mit access, reason, upgrade_url
    """
    plan = user.get('plan_type', 'free')
    limits = FeatureLimits.get_limits(plan)

    has_access = limits.get(feature, False)

    if has_access:
        return {
            'access': True,
            'plan': plan,
            'feature': feature
        }
    else:
        # Finde günstigsten Plan mit Feature
        upgrade_plan = None
        for plan_name, plan_limits in FeatureLimits.LIMITS.items():
            if plan_limits.get(feature) and plan_name != 'free':
                upgrade_plan = plan_name
                break

        return {
            'access': False,
            'plan': plan,
            'feature': feature,
            'reason': f'Feature nur in {upgrade_plan.upper()} verfügbar',
            'upgrade_plan': upgrade_plan,
            'upgrade_url': f'/upgrade?to={upgrade_plan}'
        }


def check_alert_limit(user: Dict) -> Dict:
    """
    [*] Prüft Alert-Limit

    Returns:
        Dict mit used, limit, remaining, can_create
    """
    from database import get_db, dict_cursor

    plan = user.get('plan_type', 'free')
    limits = FeatureLimits.get_limits(plan)
    alert_limit = limits['alerts']

    # Aktuelle Anzahl
    conn = get_db()
    cur = dict_cursor(conn)

    cur.execute("""
        SELECT COUNT(*) as count
        FROM search_alerts
        WHERE user_email = %s AND is_active = 1
    """, (user['email'],))

    current = cur.fetchone()['count']
    conn.close()

    if alert_limit == 'unlimited':
        return {
            'used': current,
            'limit': 'unlimited',
            'remaining': 'unlimited',
            'can_create': True,
            'plan': plan
        }

    remaining = alert_limit - current

    return {
        'used': current,
        'limit': alert_limit,
        'remaining': max(0, remaining),
        'can_create': remaining > 0,
        'plan': plan,
        'upgrade_needed': remaining <= 0
    }


def get_upgrade_benefits(from_plan: str, to_plan: str) -> Dict:
    """
    ✨ Zeigt Benefits beim Upgrade

    Args:
        from_plan: Aktueller Plan
        to_plan: Ziel-Plan

    Returns:
        Dict mit Benefits
    """
    current_limits = FeatureLimits.get_limits(from_plan)
    new_limits = FeatureLimits.get_limits(to_plan)

    benefits = []

    # Alerts
    if current_limits['alerts'] != new_limits['alerts']:
        if new_limits['alerts'] == 'unlimited':
            benefits.append({
                'feature': 'Alerts',
                'before': f"{current_limits['alerts']} Alerts",
                'after': '∞ Unbegrenzt',
                'emoji': '🔔'
            })
        else:
            benefits.append({
                'feature': 'Alerts',
                'before': f"{current_limits['alerts']} Alerts",
                'after': f"{new_limits['alerts']} Alerts",
                'emoji': '🔔'
            })

    # Check-Intervall
    if current_limits['check_interval'] != new_limits['check_interval']:
        benefits.append({
            'feature': 'Check-Geschwindigkeit',
            'before': f"Alle {current_limits['check_interval']} Min",
            'after': f"Alle {new_limits['check_interval']} Min",
            'emoji': '⚡'
        })

    # Marketplaces
    current_markets = current_limits['marketplaces']
    new_markets = new_limits['marketplaces']
    if current_markets != new_markets:
        if new_markets == 'all':
            benefits.append({
                'feature': 'Portale',
                'before': f"{len(current_markets)} Portale",
                'after': 'Alle Portale (inkl. Facebook)',
                'emoji': '🏪'
            })
        else:
            benefits.append({
                'feature': 'Portale',
                'before': f"{len(current_markets)} Portale",
                'after': f"{len(new_markets)} Portale",
                'emoji': '🏪'
            })

    # Neue Features
    new_features = []
    for feature in ['price_history', 'ai_analysis', 'whatsapp', 'priority_alerts']:
        if not current_limits.get(feature) and new_limits.get(feature):
            feature_names = {
                'price_history': 'Preisverlauf',
                'ai_analysis': 'KI-Analyse',
                'whatsapp': 'WhatsApp-Benachrichtigungen',
                'priority_alerts': 'Priority-Alerts'
            }
            new_features.append(feature_names[feature])

    if new_features:
        benefits.append({
            'feature': 'Neue Features',
            'before': '-',
            'after': ', '.join(new_features),
            'emoji': '✨'
        })

    return {
        'from_plan': from_plan,
        'to_plan': to_plan,
        'benefits': benefits,
        'price_monthly': new_limits.get('price_monthly'),
        'price_yearly': new_limits.get('price_yearly')
    }


# ===================================================================
# PAYMENT INTEGRATION (Stripe)
# ===================================================================

def create_checkout_session(
    user: Dict,
    plan: str,
    billing_cycle: str = 'monthly'
) -> Dict:
    """
    💳 Erstellt Stripe Checkout Session

    Setup:
    1. Stripe Account: https://stripe.com/
    2. Products & Prices erstellen
    3. Webhook einrichten
    4. STRIPE_SECRET_KEY in .env

    Args:
        user: User-Dict
        plan: Plan-Name (basic, pro, ultimate)
        billing_cycle: monthly oder yearly

    Returns:
        Dict mit checkout_url
    """
    try:
        import stripe

        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

        # Price IDs (aus Stripe Dashboard)
        price_ids = {
            'basic_monthly': os.getenv('STRIPE_PRICE_BASIC_MONTHLY'),
            'basic_yearly': os.getenv('STRIPE_PRICE_BASIC_YEARLY'),
            'pro_monthly': os.getenv('STRIPE_PRICE_PRO_MONTHLY'),
            'pro_yearly': os.getenv('STRIPE_PRICE_PRO_YEARLY'),
            'ultimate_monthly': os.getenv('STRIPE_PRICE_ULTIMATE_MONTHLY'),
            'ultimate_yearly': os.getenv('STRIPE_PRICE_ULTIMATE_YEARLY'),
        }

        price_id = price_ids.get(f"{plan}_{billing_cycle}")

        if not price_id:
            return {
                'success': False,
                'error': 'Price ID nicht konfiguriert'
            }

        # Checkout Session
        success_url = os.getenv('APP_URL', 'http://localhost:5000') + '/payment/success?session_id={CHECKOUT_SESSION_ID}'
        cancel_url = os.getenv('APP_URL', 'http://localhost:5000') + '/upgrade'

        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'sepa_debit', 'paypal'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=user['email'],
            metadata={
                'user_email': user['email'],
                'plan': plan,
                'billing_cycle': billing_cycle
            }
        )

        return {
            'success': True,
            'checkout_url': session.url,
            'session_id': session.id
        }

    except Exception as e:
        log.error(f"Stripe error: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def handle_stripe_webhook(payload: str, sig_header: str) -> Dict:
    """
    🔔 Stripe Webhook Handler

    Wird aufgerufen wenn:
    - Payment erfolgreich
    - Subscription erneuert
    - Subscription gekündigt

    Args:
        payload: Request body
        sig_header: Stripe-Signature header

    Returns:
        Status Dict
    """
    try:
        import stripe

        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

        # Verify Signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )

        # Handle Events
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            _handle_successful_payment(session)

        elif event['type'] == 'customer.subscription.updated':
            subscription = event['data']['object']
            _handle_subscription_updated(subscription)

        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            _handle_subscription_cancelled(subscription)

        return {'success': True, 'event_type': event['type']}

    except Exception as e:
        log.error(f"Webhook error: {e}")
        return {'success': False, 'error': str(e)}


def _handle_successful_payment(session: Dict):
    """Upgrade User nach erfolgreicher Zahlung"""
    from database import get_db, get_placeholder

    user_email = session['metadata']['user_email']
    plan = session['metadata']['plan']

    conn = get_db()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"""
        UPDATE users
        SET plan_type = {ph},
            subscription_id = {ph},
            subscription_start = {ph}
        WHERE email = {ph}
    """, (plan, session['subscription'], datetime.now(), user_email))

    conn.commit()
    conn.close()

    log.info(f"[OK] User {user_email} upgraded to {plan}")


def _handle_subscription_updated(subscription: Dict):
    """Handle Subscription Updates"""
    # Status-Änderungen, Plan-Änderungen, etc.
    log.info(f"Subscription updated: {subscription['id']}")


def _handle_subscription_cancelled(subscription: Dict):
    """Downgrade User bei Kündigung"""
    from database import get_db, get_placeholder

    conn = get_db()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"""
        UPDATE users
        SET plan_type = 'free',
            subscription_id = NULL,
            subscription_end = {ph}
        WHERE subscription_id = {ph}
    """, (datetime.now(), subscription['id']))

    conn.commit()
    conn.close()

    log.info(f"User downgraded to free (subscription cancelled)")


# ===================================================================
# TRIAL PERIOD
# ===================================================================

def activate_trial(user: Dict, plan: str = 'pro', days: int = 7) -> Dict:
    """
    🎁 Aktiviert Trial-Period

    Args:
        user: User-Dict
        plan: Welcher Plan zum Testen
        days: Anzahl Tage

    Returns:
        Status Dict
    """
    from database import get_db, get_placeholder

    trial_end = datetime.now() + timedelta(days=days)

    conn = get_db()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"""
        UPDATE users
        SET plan_type = {ph},
            trial_until = {ph},
            trial_active = 1
        WHERE email = {ph}
    """, (plan, trial_end, user['email']))

    conn.commit()
    conn.close()

    return {
        'success': True,
        'plan': plan,
        'trial_days': days,
        'trial_until': trial_end.isoformat()
    }


def check_trial_status(user: Dict) -> Dict:
    """Prüft Trial-Status"""
    if not user.get('trial_active'):
        return {'active': False}

    trial_until = user.get('trial_until')
    if not trial_until:
        return {'active': False}

    if isinstance(trial_until, str):
        from dateutil.parser import parse
        trial_until = parse(trial_until)

    is_active = datetime.now() < trial_until
    days_remaining = (trial_until - datetime.now()).days

    return {
        'active': is_active,
        'plan': user.get('plan_type'),
        'until': trial_until.isoformat(),
        'days_remaining': max(0, days_remaining)
    }


# ===================================================================
# REFERRAL PROGRAM (Empfehlungsprogramm)
# ===================================================================

def generate_referral_code(user: Dict) -> str:
    """Generiert Referral-Code"""
    import hashlib
    code = hashlib.md5(f"{user['email']}_{user['id']}".encode()).hexdigest()[:8]
    return code.upper()


def track_referral(referrer_code: str, new_user_email: str) -> Dict:
    """
    🎁 Tracked Referral

    Belohnung:
    - Referrer: 1 Monat kostenlos
    - New User: 14 Tage Trial
    """
    from database import get_db, get_placeholder

    conn = get_db()
    cur = conn.cursor()
    ph = get_placeholder()

    # Finde Referrer
    cur.execute(f"""
        SELECT * FROM users WHERE referral_code = {ph}
    """, (referrer_code,))

    referrer = cur.fetchone()

    if not referrer:
        return {'success': False, 'error': 'Invalid referral code'}

    # Gib Referrer Bonus
    cur.execute(f"""
        UPDATE users
        SET trial_until = DATE_ADD(COALESCE(trial_until, NOW()), INTERVAL 30 DAY)
        WHERE referral_code = {ph}
    """, (referrer_code,))

    conn.commit()
    conn.close()

    log.info(f"Referral tracked: {referrer['email']} -> {new_user_email}")

    return {
        'success': True,
        'referrer_bonus': '30 days',
        'new_user_bonus': '14 days trial'
    }


# ===================================================================
# USAGE STATS (für User Dashboard)
# ===================================================================

def get_usage_stats(user: Dict) -> Dict:
    """
    [*] Holt Usage-Statistiken für User

    Returns:
        Dict mit Stats
    """
    from database import get_db, dict_cursor

    plan_limits = FeatureLimits.get_limits(user.get('plan_type', 'free'))

    conn = get_db()
    cur = dict_cursor(conn)

    # Alert-Count
    cur.execute("""
        SELECT COUNT(*) as count
        FROM search_alerts
        WHERE user_email = %s AND is_active = 1
    """, (user['email'],))
    alert_count = cur.fetchone()['count']

    # Watchlist-Count
    cur.execute("""
        SELECT COUNT(*) as count
        FROM watchlist
        WHERE user_email = %s
    """, (user['email'],))
    watchlist_count = cur.fetchone()['count']

    # Notification-Count (letzte 30 Tage)
    cur.execute("""
        SELECT COUNT(*) as count
        FROM notification_log
        WHERE user_email = %s
          AND sent_at > NOW() - INTERVAL 30 DAY
    """, (user['email'],))
    notification_count = cur.fetchone()['count']

    conn.close()

    return {
        'plan': user.get('plan_type', 'free'),
        'alerts': {
            'used': alert_count,
            'limit': plan_limits['alerts'],
            'percentage': (alert_count / plan_limits['alerts'] * 100) if plan_limits['alerts'] != 'unlimited' else 0
        },
        'watchlist': {
            'used': watchlist_count,
            'limit': plan_limits['watchlist_items']
        },
        'notifications_30d': notification_count,
        'check_interval': plan_limits['check_interval'],
        'marketplaces': plan_limits['marketplaces']
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test
    print("\n💎 PREMIUM FEATURES TEST\n")

    # Mock User
    free_user = {'email': 'test@test.com', 'plan_type': 'free'}
    pro_user = {'email': 'pro@test.com', 'plan_type': 'pro'}

    print("1️⃣  Feature-Check (Free User -> AI Analysis):")
    result = check_feature_access(free_user, 'ai_analysis')
    print(f"   {result}\n")

    print("2️⃣  Upgrade Benefits (Free -> Pro):")
    benefits = get_upgrade_benefits('free', 'pro')
    for benefit in benefits['benefits']:
        print(f"   {benefit['emoji']} {benefit['feature']}: {benefit['before']} -> {benefit['after']}")
    print(f"   💰 Price: {benefits['price_monthly']}€/Monat\n")

    print("3️⃣  Plan Comparison:")
    for plan_name, limits in FeatureLimits.LIMITS.items():
        print(f"   {plan_name.upper():10} {limits['alerts']:10} Alerts, {limits['check_interval']} Min Check")
