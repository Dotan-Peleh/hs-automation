import os
from datetime import datetime, timedelta

WINDOW_MIN = int(os.getenv("WINDOW_SIZE_MIN", "360"))
BASELINE_DAYS = int(os.getenv("BASELINE_DAYS", "7"))

_state = {}

def update_and_score(cluster_key: str):
    now = datetime.utcnow()
    wstart = now - timedelta(minutes=WINDOW_MIN)
    recs = _state.get(cluster_key, [])
    recs = [t for t in recs if t > wstart]
    recs.append(now)
    _state[cluster_key] = recs

    vol = len(recs)
    baseline = max(1.0, vol / 3.5)
    z = (vol - baseline) / max(1.0, baseline ** 0.5)
    cusum = max(0.0, (vol - baseline))
    return float(z), float(cusum)
