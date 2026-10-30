"""Non-network diagnostics: eight providers, model-family independence and free confirmation.

Configured keys do not certify live connectivity, free billing or remaining quota.
"""
from __future__ import annotations
import os
from council.families import FAMILIES
from model_router import KEY_NAMES

CONFIRM = {"Cohere":"COHERE_TRIAL_CONFIRMED",
           "Ollama Cloud":"OLLAMA_FREE_CONFIRMED"}

def provider_coverage(*, env=None, active_families=()) -> dict:
    variables = env if env is not None else os.environ
    active = set(active_families)
    if not active <= set(FAMILIES):
        raise ValueError("Unknown active model families")
    providers = {}
    for family_name, family in FAMILIES.items():
        for endpoint in family.endpoints:
            provider = endpoint.provider
            if provider not in KEY_NAMES or provider == "NVIDIA NIM":
                continue
            entry = providers.setdefault(provider, {
                "status":"not_configured", "families":[],
                "in_run":False, "free_confirmed":False, "live_checked":False,
                "eligible_for_attempt":False})
            if family_name not in entry["families"]:
                entry["families"].append(family_name)
            entry["in_run"] |= family_name in active
            key_ok = bool(str(variables.get(KEY_NAMES[provider],"")).strip())
            if provider == "Cloudflare":
                key_ok &= bool(str(variables.get("CLOUDFLARE_ACCOUNT_ID","")).strip())
            flag = CONFIRM.get(provider)
            confirmed = flag is None or str(variables.get(flag,"")) == "1"
            entry["free_confirmed"] = bool(confirmed)
            entry["eligible_for_attempt"] |= bool(key_ok and confirmed)
            if key_ok:
                entry["status"] = ("configured_unverified" if confirmed
                                   else "free_confirmation_required")
    active_eligible=sorted(
        family for family in active
        if any(providers.get(ep.provider,{}).get("eligible_for_attempt",False)
               for ep in FAMILIES[family].endpoints))
    return {
        "providers":dict(sorted(providers.items())),
        "active_attempt_eligible_families":active_eligible,
        "active_not_ready_families":sorted(active - set(active_eligible)),
        "provider_count":len(providers),
        "family_count":len(FAMILIES),
        "active_family_count":len(active),
        "quorum_eligible_families":sorted(
            k for k,v in FAMILIES.items() if v.counts_for_quorum),
        "limitations":[
            "Eligible for attempt means an API key and required free-mode "
            "confirmation exist; it does NOT confirm provider uptime or quota.",
            "No live request was made; actual free eligibility and quotas remain unverified.",
            "A model lineage served by two providers counts as one family.",
            "Role reservations prevent calling all endpoints in every run.",
        ]
    }
