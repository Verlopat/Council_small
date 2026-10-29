"""Mutation testing of generated specifications, with equivalent-mutant diagnostics."""
from __future__ import annotations
import ast
from dataclasses import dataclass
import re

_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_SWAPS = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Sub,
          ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE,
          ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}

def numeric_mutants(text: str, limit: int = 8) -> list[str]:
    m = _NUM.search(text)
    if m is None:
        return []
    number = float(m.group())
    candidates = (number + 1, number - 1, -number, number + .5, number * 10)
    def fmt(value):
        return str(int(value)) if value.is_integer() else str(value)
    out = []
    for candidate in candidates:
        v = fmt(candidate)
        altered = text[:m.start()] + v + text[m.end():]
        if altered != text and altered not in out:
            out.append(altered)
    return out[:limit]

class _Mutate(ast.NodeTransformer):
    def __init__(self, site):
        self.site, self.current, self.changed = site, 0, False
    def _visit_op(self, node, attr):
        op = getattr(node, attr)
        if type(op) in _SWAPS:
            if self.current == self.site:
                setattr(node, attr, _SWAPS[type(op)]())
                self.changed = True
            self.current += 1
        return node
    def visit_BinOp(self, node):
        self.generic_visit(node)
        return self._visit_op(node, "op")
    def visit_Compare(self, node):
        self.generic_visit(node)
        if node.ops:
            op = node.ops[0]
            if type(op) in _SWAPS:
                if self.current == self.site:
                    node.ops[0] = _SWAPS[type(op)]()
                    self.changed = True
                self.current += 1
        return node
    def visit_Constant(self, node):
        if type(node.value) is int:
            if self.current == self.site:
                node.value += 1
                self.changed = True
            self.current += 1
        return node

def code_mutants(code: str, limit: int = 8) -> list[str]:
    try:
        ast.parse(code)
    except SyntaxError:
        return []
    outputs = []
    for i in range(limit):
        tree = ast.parse(code)
        mutator = _Mutate(i)
        mutator.visit(tree)
        if not mutator.changed:
            break
        altered = ast.unparse(ast.fix_missing_locations(tree))
        if altered not in outputs and altered != code:
            outputs.append(altered)
    return outputs

@dataclass(frozen=True)
class MutationAssessment:
    discriminating: bool
    surviving: tuple[str, ...]
    invalid: tuple[str, ...]
    note: str

def assess(run_check, original: str, mutants: list[str]) -> MutationAssessment:
    if run_check(original) != "pass":
        return MutationAssessment(False, (), (), "original did not pass")
    if not mutants:
        return MutationAssessment(False, (), (), "no useful mutants generated")
    survived, invalid = [], []
    for mutant in mutants:
        outcome = run_check(mutant)
        if outcome == "pass":
            survived.append(mutant)
        elif outcome in {"error", "timeout"}:
            invalid.append(mutant)
    return MutationAssessment(not survived and not invalid, tuple(survived),
                              tuple(invalid),
                              "Surviving mutants need analysis: weak check OR equivalent mutation; do not automatically refute a claim")
