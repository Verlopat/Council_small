"""Avoid false independence when caching across runs and generation settings."""
import hashlib
import json

def response_cache_key(*, provider: str, model: str, messages: list[dict],
                       settings: dict, prompt_version: str, sample_id: str) -> str:
    encoded = json.dumps({
        "provider": provider, "model": model, "messages": messages,
        "settings": settings, "prompt_version": prompt_version,
        "sample_id": sample_id,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
