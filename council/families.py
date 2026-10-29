"""Allowlisted, role-reserved model families; endpoints are not independent votes."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Endpoint:
    provider: str
    model: str

@dataclass(frozen=True)
class Family:
    name: str
    endpoints: tuple[Endpoint, ...]
    counts_for_quorum: bool = True

FAMILIES: dict[str, Family] = {
    "gpt-oss": Family("gpt-oss", (Endpoint("Groq", "openai/gpt-oss-120b"),)),
    "command": Family("command", (Endpoint("Cohere", "command-a-plus-05-2026"),
                                  Endpoint("Cohere", "command-a-03-2025"))),
    "nemotron": Family("nemotron", (Endpoint("OpenRouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                                    Endpoint("LLM7.io", "nemotron-3-nano:30b"))),
    "gemma": Family("gemma", (Endpoint("Ollama Cloud", "gemma4:31b"),)),
    "gemini": Family("gemini", (Endpoint("Gemini", "gemini-3.6-flash"),
                               Endpoint("Gemini", "gemini-3.5-flash-lite"),
                               Endpoint("Gemini", "gemini-3.8-flash"),
                               Endpoint("Gemini", "gemini-3.7-flash"))),
    "glm": Family("glm", (Endpoint("Z.ai", "glm-4.7-flash"),
                         Endpoint("Cloudflare", "@cf/zai-org/glm-4.7-flash"))),
    "minimax": Family("minimax", (Endpoint("LLM7.io", "minimax-m2.7"),),
                      counts_for_quorum=False),
}

def validate_assignment(solvers: tuple[str, ...], judge: str, auditor: str) -> None:
    if len(set(solvers)) != len(solvers):
        raise ValueError("Solver families must be distinct")
    if len(solvers) < 1 or any(f not in FAMILIES for f in (*solvers, judge, auditor)):
        raise ValueError("Unknown or missing model family")
    if judge in solvers or judge == auditor:
        raise ValueError("Judge family must be reserved and isolated")
    if auditor in solvers:
        raise ValueError("Auditor family must be separate from solvers")

def quorum(families: set[str]) -> int:
    return sum(FAMILIES[f].counts_for_quorum for f in families)

def endpoint_list(family: str) -> tuple[Endpoint, ...]:
    return FAMILIES[family].endpoints
