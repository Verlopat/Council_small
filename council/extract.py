"""Rung-0 raw extraction and source-anchored claims, without claiming truth."""
from __future__ import annotations
from dataclasses import dataclass
import json
import re
import unicodedata

THINK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.I | re.S)
QUANTIFIERS = re.compile(
    r"\b(for all|for every|there exists|exists|any|always|never|may|might|must|"
    r"with (?:overwhelming|negligible) probability|under (?:the )?assumption|"
    r"except|unless|only if|if and only if)\b", re.I)

def raw_text(body: dict) -> str:
    if not isinstance(body, dict):
        return ""
    options = []
    try:
        message = body["choices"][0]["message"]
        if isinstance(message, dict):
            options.extend([message.get("content"), message.get("reasoning_content"),
                            message.get("reasoning")])
    except (KeyError, IndexError, TypeError):
        pass
    if "candidates" in body:
        for candidate in body.get("candidates") or []:
            content = candidate.get("content") or {}
            options.append("\n".join(p.get("text", "") for p in content.get("parts", [])
                                     if isinstance(p, dict)))
    message = body.get("message")
    if isinstance(message, dict):
        options.append(message.get("content"))
    result = body.get("result")
    if isinstance(result, dict):
        options.append(result.get("response"))
    for raw in options:
        if isinstance(raw, list):
            raw = "\n".join(p.get("text", "") for p in raw if isinstance(p, dict)
                             and isinstance(p.get("text"), str))
        if isinstance(raw, str) and raw.strip():
            cleaned = THINK.sub("", raw).strip()
            if cleaned:
                return cleaned
    return ""

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return " ".join(s.replace("\u202f", " ").replace("\u2009", " ")
                    .replace("\u2212", "-").split()).strip()

def final_number(s: str) -> str | None:
    """Extract only when the final line is clearly a number/answer; avoid 156 in unrelated prose."""
    lines = [x.strip().replace("**", "") for x in normalize(s).splitlines() if x.strip()]
    if not lines:
        return None
    match = re.fullmatch(r"(?:answer|result)\s*[:=]\s*([+-]?\d+(?:\.\d+)?)\.?|([+-]?\d+(?:\.\d+)?)", lines[-1], re.I)
    return match.group(1) or match.group(2) if match else None

@dataclass(frozen=True)
class AnchoredClaim:
    statement: str
    source_span: str
    answer_hash: str
    assumptions: tuple[str, ...]
    quantifiers: tuple[str, ...]
    depends_on: tuple[str, ...]

def validate_anchor(answer: str, statement: str, span: str,
                    *, assumptions: list[str] | None = None,
                    depends_on: list[str] | None = None) -> AnchoredClaim:
    from hashlib import sha256
    if not statement.strip() or not span.strip() or span not in answer:
        raise ValueError("Claim requires exact quoted source span")
    original_q = tuple(sorted(set(m.group(0).lower() for m in QUANTIFIERS.finditer(span))))
    rewritten_q = tuple(sorted(set(m.group(0).lower() for m in QUANTIFIERS.finditer(statement))))
    if original_q != rewritten_q:
        raise ValueError("Quantifier or modality changed between source and claim")
    return AnchoredClaim(statement.strip(), span,
                         sha256(answer.encode()).hexdigest(),
                         tuple(assumptions or ()), original_q, tuple(depends_on or ()))

def conservative_merge_key(claim: AnchoredClaim) -> tuple:
    """Candidate duplicates only; matching keys do not certify logical equivalence."""
    return (normalize(claim.statement).casefold(), claim.assumptions,
            claim.quantifiers)
