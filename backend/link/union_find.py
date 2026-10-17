"""Connected components over LINKED edges (ADR-002). Pure; rebuilt from scratch per change."""
from __future__ import annotations

from collections.abc import Hashable, Iterable


def components[N: Hashable](edges: Iterable[tuple[N, N]], nodes: Iterable[N] = ()) -> dict[N, frozenset[N]]:
    """Map every node to its component. Singletons map to a one-element set."""
    parent: dict[N, N] = {}

    def find(x: N) -> N:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    for n in nodes:
        find(n)
    groups: dict[N, set[N]] = {}
    for n in parent:
        groups.setdefault(find(n), set()).add(n)
    return {n: frozenset(members) for members in groups.values() for n in members}


def component_of[N: Hashable](edges: Iterable[tuple[N, N]], node: N) -> frozenset[N]:
    return components(edges, [node])[node]
