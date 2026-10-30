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
    if not isinstance(s, str):
        return None
    # Normalize each line separately; normalizing first collapses newlines and
    # can accidentally confuse incidental numeric citations with the answer.
    lines = [normalize(line).replace("**", "").replace("`", "").strip()
             for line in s.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1].rstrip(".! ").replace(",", "")
    number = r"([+-]?[0-9]+(?:[.][0-9]+)?)"
    patterns = (
        rf"{number}",
        rf"(?:the[ ]+)?(?:final[ ]+)?(?:answer|result)[ ]*(?::|is|=)[ ]*{number}",
        rf".+[ ](?:=|equals)[ ]*{number}",
    )
    for pattern in patterns:
        found = re.fullmatch(pattern, last, flags=re.I)
        if found:
            return found.group(found.lastindex)
    return None

@dataclass(frozen=True)
class AnchoredClaim:
    statement: str
    source_span: str
    answer_hash: str
    assumptions: tuple[str, ...]
    quantifiers: tuple[str, ...]
    depends_on: tuple[str, ...]

# Narrow, reversible *formatting* equivalences. Never lowercase variable names,
# delete words, reorder tokens, or accept paraphrases as source provenance.
_FORMAT_DASH = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")
_FORMAT_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'",
                                "\u201c": '"', "\u201d": '"'})
_TEX_TOKENS = {
    r"\neq": "≠", r"\ne": "≠", r"\leq": "≤", r"\geq": "≥",
    r"\in": "∈", "^{*}": "*", "^*": "*",
}


def _locate_chars(source: str) -> tuple[str, list[tuple[int, int]]]:
    """Return a canonical rendering and offsets back to the original source."""
    out: list[str] = []
    offsets: list[tuple[int, int]] = []
    i = 0
    while i < len(source):
        start = i
        token = None
        for lhs, rhs in _TEX_TOKENS.items():
            if source.startswith(lhs, i):
                end = i + len(lhs)
                if lhs.startswith("\\") and end < len(source) and source[end].isalpha():
                    continue
                token = rhs
                i = end
                break
        if token is None:
            if source.startswith("**", i):
                i += 2
                continue
            if source.startswith(r"\(", i) or source.startswith(r"\)", i):
                i += 2
                continue
            token = source[i]
            i += 1
            if token in ("$", chr(96)):
                continue
        token = unicodedata.normalize("NFKC", token)
        token = token.translate(_FORMAT_DASH).translate(_FORMAT_QUOTES)
        for ch in token:
            if ch.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
                    offsets.append((start, i))
            else:
                out.append(ch)
                offsets.append((start, i))
    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    # Spaces around mathematical relational operators are presentation;
    # spaces separating ordinary words remain significant.
    packed, packed_offsets = [], []
    for j, ch in enumerate(out):
        if ch == " " and (
                (j > 0 and out[j-1] in "≠≤≥∈") or
                (j+1 < len(out) and out[j+1] in "≠≤≥∈")):
            continue
        packed.append(ch)
        packed_offsets.append(offsets[j])
    return "".join(packed), packed_offsets


def numbered_sentence_excerpt(answer: str, sentence_ids: list[int]) -> str | None:
    """Find exact original text from sequential [S1] labels.

    Provenance only. This does not establish semantic alignment.
    """
    if (not sentence_ids or len(sentence_ids) > 8 or
        any(type(i) is not int or i < 1 or i > 100 for i in sentence_ids) or
        sentence_ids != list(range(sentence_ids[0], sentence_ids[-1]+1))):
        return None
    pattern = r"(?m)^\s*\[S([1-9][0-9]*)\]\s+"
    tags = list(re.finditer(pattern, answer))
    table = {}
    for position, tag in enumerate(tags):
        number = int(tag.group(1))
        if number in table:
            return None
        stop = tags[position+1].start() if position+1 < len(tags) else len(answer)
        table[number] = (tag.end(), stop)
    if any(number not in table for number in sentence_ids):
        return None
    return answer[table[sentence_ids[0]][0]:table[sentence_ids[-1]][1]].strip()


def locate_source_span(answer: str, span: str) -> str | None:
    """Find formatting-equivalent text and return original, unmodified bytes.

    This permits only bounded Unicode/TeX formatting substitutions. It never
    considers a paraphrase or an LLM-supplied semantic equivalence sufficient.
    """
    if not isinstance(answer, str) or not isinstance(span, str) or not span.strip():
        return None
    if span in answer:
        return span
    normalized_answer, offsets = _locate_chars(answer)
    normalized_span, _ = _locate_chars(span)
    if not normalized_span or not offsets:
        return None
    where = normalized_answer.find(normalized_span)
    if where < 0:
        return None
    end = where + len(normalized_span) - 1
    if end >= len(offsets):
        return None
    return answer[offsets[where][0]:offsets[end][1]]


def validate_anchor(answer: str, statement: str, span: str,
                    *, assumptions: list[str] | None = None,
                    depends_on: list[str] | None = None) -> AnchoredClaim:
    from hashlib import sha256
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("Claim requires a nonempty statement")
    actual_span = locate_source_span(answer, span)
    if actual_span is None:
        raise ValueError("Claim requires an exact or formatting-equivalent source span")
    original_q = tuple(sorted(set(m.group(0).lower() for m in QUANTIFIERS.finditer(actual_span))))
    rewritten_q = tuple(sorted(set(m.group(0).lower() for m in QUANTIFIERS.finditer(statement))))
    if original_q != rewritten_q:
        raise ValueError("Quantifier or modality changed between source and claim")
    return AnchoredClaim(statement.strip(), actual_span,
                         sha256(answer.encode()).hexdigest(),
                         tuple(assumptions or ()), original_q, tuple(depends_on or ()))

def conservative_merge_key(claim: AnchoredClaim) -> tuple:
    """Candidate duplicates only; matching keys do not certify logical equivalence."""
    return (normalize(claim.statement).casefold(), claim.assumptions,
            claim.quantifiers)

def suggest_duplicate_claims(claims, *, threshold: float = 0.85) -> list[dict]:
    """Review-only semantic-neighborhood hints; never merge different claims.

    Even a score of 1.0 is not logical equivalence. `safe_to_merge` is
    deliberately limited to exact normalized statements AND equal assumption,
    quantifier and scope metadata. The caller remains responsible for explicit
    human or independent semantic review.
    """
    from difflib import SequenceMatcher
    if not 0 <= threshold <= 1:
        raise ValueError("Similarity threshold out of bounds")
    rows = list(claims)
    if len(rows) > 1000:
        raise ValueError("Too many claims for pairwise comparison")
    hints = []
    for i, a in enumerate(rows):
        for b in rows[i+1:]:
            left = normalize(a.statement).casefold()
            right = normalize(b.statement).casefold()
            score = SequenceMatcher(None, left, right, autojunk=False).ratio()
            if score < threshold:
                continue
            equal_semantic_bounds = (
                left == right and tuple(a.assumptions) == tuple(b.assumptions)
                and tuple(a.quantifiers) == tuple(b.quantifiers)
                and a.scope == b.scope)
            hints.append({"first_id":a.id,"second_id":b.id,
                          "similarity":round(score,4),
                          "metadata_equal":equal_semantic_bounds,
                          "action":"review_only"})
    return hints
