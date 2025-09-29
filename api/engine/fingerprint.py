import hashlib

def cluster_key(text: str, entities: dict) -> str:
    sig = f"{text.lower()}|{entities.get('level')}|{entities.get('platform')}|{entities.get('app_version')}"
    return hashlib.md5(sig.encode("utf-8")).hexdigest()
