"""Versioned dependency edges, argument provenance and transitive invalidation.

A premise losing support invalidates the ARGUMENT that used it, never
automatically the conclusion as a mathematical proposition.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict, deque

@dataclass
class Dependency:
    premise_id: str
    premise_version: int
    dependent_id: str
    dependent_version: int
    argument: str
    valid_support: bool = True
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (not self.premise_id or not self.dependent_id or
                self.premise_version < 1 or self.dependent_version < 1 or
                not self.argument.strip() or self.premise_id == self.dependent_id):
            raise ValueError("Dependency requires two distinct versioned claims and an argument")

class DependencyGraph:
    def __init__(self):
        self.edges: list[Dependency] = []

    def add(self, edge: Dependency, *, claims: dict) -> None:
        premise=claims.get(edge.premise_id)
        dependent=claims.get(edge.dependent_id)
        if premise is None or dependent is None:
            raise ValueError("Dependency refers to a missing claim")
        if (edge.premise_version != premise.version or
            edge.dependent_version != dependent.version):
            raise ValueError("Dependency version mismatch")
        if any(e.premise_id==edge.premise_id and e.dependent_id==edge.dependent_id
               and e.valid_support for e in self.edges):
            raise ValueError("Active argument already recorded for this edge")
        if self._reachable(edge.dependent_id, edge.premise_id):
            raise ValueError("Circular derivation not permitted")
        self.edges.append(edge)

    def _reachable(self, start: str, target: str) -> bool:
        seen=set();queue=deque([start])
        while queue:
            node=queue.popleft()
            if node==target:return True
            if node in seen:continue
            seen.add(node)
            queue.extend(e.dependent_id for e in self.edges
                         if e.valid_support and e.premise_id==node)
        return False

    def invalidate(self, premise_id: str) -> set[str]:
        affected=set()
        queue=deque([premise_id])
        visited=set()
        while queue:
            node=queue.popleft()
            if node in visited:continue
            visited.add(node)
            for edge in self.edges:
                if edge.premise_id != node or not edge.valid_support:
                    continue
                edge.valid_support=False
                affected.add(edge.dependent_id)
                queue.append(edge.dependent_id)
        return affected

    def live_edges(self, claim_id: str) -> list[Dependency]:
        return [e for e in self.edges if e.dependent_id==claim_id and e.valid_support]

    def claim_dependencies(self, claim_id: str) -> tuple[str, ...]:
        return tuple(e.premise_id for e in self.live_edges(claim_id))
