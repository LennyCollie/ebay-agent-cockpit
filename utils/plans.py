# utils/plans.py
PLAN_LIMITS = {
    "free": {"agents": 3, "interval_s": 300, "telegram": False, "label": "Free"},
    "basic": {"agents": 10, "interval_s": 90, "telegram": True, "label": "Basic"},
    "pro": {"agents": 30, "interval_s": 30, "telegram": True, "label": "Pro"},
    "team": {"agents": 100, "interval_s": 15, "telegram": True, "label": "Team"},
}


def plan_name(user) -> str:
    try:
        return (user.plan or "free").lower()
    except Exception:
        return "free"


def limit(user, key):
    return PLAN_LIMITS[plan_name(user)][key]
