import os

Z_MED=float(os.getenv("Z_THRESH_MEDIUM","1.8"))
Z_HIGH=float(os.getenv("Z_THRESH_HIGH","2.5"))
Z_CRIT=float(os.getenv("Z_THRESH_CRITICAL","3.5"))
SLACK_MIN=int(os.getenv("SEVERITY_NOTIFY_SLACK_MIN","40"))

def compute(text: str, entities: dict, rule_score: int) -> int:
    """Return a 0-100 severity score.
    Heuristic boost on top of rule_score so we get low/medium/high variety.
    """
    t = (text or "").lower()
    score = int(rule_score or 0)
    # High-impact keywords
    if any(k in t for k in ("crash", "crashing", "force close", "exception", "won't open", "cannot open")):
        score += 35
    if any(k in t for k in ("progress lost", "lost progress", "save lost", "wipe", "reset progress")):
        score += 30
    if any(k in t for k in ("payment", "purchase", "charged", "refund", "billing", "iap", "subscription")):
        score += 25
    if any(k in t for k in ("can't login", "cannot login", "login failed", "account locked", "account delete")):
        score += 20
    if any(k in t for k in ("data loss", "corrupt", "duplicate charge", "unable to play", "unplayable")):
        score += 20
    if any(k in t for k in ("urgent", "asap", "immediately", "critical")):
        score += 10
    # Entity-based bumps
    if isinstance(entities, dict):
        if entities.get("platform") in ("android", "ios") and any(x in t for x in ("new version", "update", "beta")):
            score += 5
        if isinstance(entities.get("level"), int) and entities.get("level", 0) >= 10:
            score += 5
    return max(0, min(100, score))

def bucketize(score: int, z: float, cusum: float):
    if (z >= Z_CRIT and score >= 40) or score >= 70:
        return "critical"
    if (z >= Z_HIGH and score >= 30) or score >= 40:
        return "high"
    if (z >= Z_MED and score >= 20):
        return "medium"
    return None
