import re

CATEGORY_PATTERNS = {
    "bug":        [r"\b(crash|freeze|stuck|black screen|blank screen|exception|error)\b"],
    "payment":    [r"\b(purchase|billing|charge|refund|declined|credit card|paypal)\b"],
    "performance":[r"\b(lag|slow|fps|frame drop|loading time|load time)\b"],
    "ux":         [r"\b(confusing|unclear|too many steps|don'?t understand)\b"],
    "account":    [r"\b(login|signin|password|auth|verification)\b"],
    "store":      [r"\b(store|iap|ads|ad\s*watch|rewarded)\b"],
    "device":     [r"\b(android|ios|iphone|ipad|samsung|xiaomi|pixel|huawei)\b"],
}

WEIGHTS = {
    r"\b(crash|freeze|stuck|exception|error)\b": 30,
    r"\b(black|blank) screen\b": 25,
    r"\b(can'?t|cannot)\s*(open|start|load|login|play|purchase)\b": 20,
    r"\b(billing|charge|refund|declined|payment)\b": 25,
    r"\b(level\s*\d+|chapter\s*\d+)\b": 5,
    r"\b(android|ios|iphone|ipad|samsung|xiaomi|pixel|huawei)\b": 5,
    r"\b(v?\d+\.\d+(?:\.\d+)*)\b": 5,
    r"\b(many|everyone|multiple|dozens|hundreds)\b": 10,
}

def extract_entities(text: str) -> dict:
    t = text.lower()
    level = re.search(r"\blevel\s*(\d{1,4})\b", t)
    chapter = re.search(r"\bchapter\s*(\d{1,4})\b", t)
    platform = "android" if re.search(r"\bandroid\b", t) else ("ios" if re.search(r"\bios\b|\biphone|\bipad", t) else None)
    app_version = re.search(r"\bv?(\d+\.\d+(?:\.\d+)*)\b", t)
    return {
        "level": int(level.group(1)) if level else None,
        "chapter": int(chapter.group(1)) if chapter else None,
        "platform": platform,
        "app_version": app_version.group(1) if app_version else None
    }

def categorize(text: str):
    t = text.lower()
    cats = []
    for cat, pats in CATEGORY_PATTERNS.items():
        if any(re.search(p, t, re.I) for p in pats):
            cats.append(cat)
    score = 0
    for pat, w in WEIGHTS.items():
        matches = re.findall(pat, t, flags=re.I)
        if matches: score += len(matches) * w
    return (cats or ["uncategorized"]), min(score, 100)
