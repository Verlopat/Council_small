"""Reject non-answer task lists when a model was asked to explain a concept.

This is a presentation/coverage heuristic, NOT a truth or security checker.
"""
from __future__ import annotations
import re

TASK_START=re.compile(
    r"^(?:\[S\d+\]\s*)?(?:define|describe|specify|formulate|outline|detail|enumerate|list|"
    r"summarize|propose|compare|identify|provide|state|critically evaluate|"
    r"develop|construct|explain how to)\b",re.I)
REQUEST=re.compile(
    r"\b(?:explain|define|describe|provide\s+(?:a\s+)?rigorous\s+analysis|"
    r"what\s+(?:is|are))\b",re.I)
TASK_REQUEST=re.compile(
    r"\b(?:plan|roadmap|research agenda|steps to|how (?:should|can|to) "
    r"(?:build|develop|implement|research))\b",re.I)
# An imperative opening can still be followed by the *actual* definition.
# Reject a checklist, not a fully specified security game whose first
# word is e.g. "Define" or "Describe".
ANSWER_DETAIL=re.compile(
    r"\b(?:is\s+(?:the|a|defined)|means|requires?|ensures?|assumes?|"
    r"the\s+adversary\s+(?:receives|chooses|produces|wins|outputs)|"
    r"vrf_verify|beta[12]?\s*(?:!=|≠)|challenge\s+output\s+is|"
    r"two\s+different\s+(?:valid\s+)?outputs?)\b",re.I)


def is_plan_instead_of_answer(question: str, approach: str) -> bool:
    if not isinstance(approach,str) or not REQUEST.search(question):
        return False
    if TASK_REQUEST.search(question):
        return False
    # Providers may write [S1], [S2], [S3] on one physical line.
    lines=[line.strip() for line in
           re.split(r"\n+|(?=\[S\d+\])", approach) if line.strip()]
    # A lone short imperative ([S1] Define all three games ...) is a
    # disguised task list. A substantive one-line *answer* remains valid.
    if len(lines)==1:
        return (len(lines[0])<200 and bool(TASK_START.match(lines[0]))
                and not bool(ANSWER_DETAIL.search(lines[0])))
    # Do not reject occasional legitimate imperative wording in a
    # substantive two-line explanation.
    if len(lines)<3:
        return False
    tasks=sum(bool(TASK_START.match(line)) and not ANSWER_DETAIL.search(line)
              for line in lines)
    return tasks>=3 and tasks/len(lines)>=0.6
