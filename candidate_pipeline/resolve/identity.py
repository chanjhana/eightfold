"""Identity resolution (PRD §7): O(n) blocking then precision linking.

Blocking (high recall, union of keys) groups candidate records that *might* be
the same person; linking (precision) decides which actually are. No pairwise
fuzzy comparison across all records — only within a shared block.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from candidate_pipeline.models.source_record import SourceRecord

# Linking constants (PRD §7.2) — positive-evidence tiers, never a weighted sum,
# and we never penalize mismatches on time-varying attributes.
INITIAL_MATCH = 0.60  # baseline when merely blocked together
NAME_STRONG = 0.85  # strong name-token alignment
NAME_WITH_CORROB = 0.70  # name alignment + a corroborating signal (shared phone)
LINK_THRESHOLD = 0.70  # >= links into the same cluster


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def name_block_key(name: str) -> str:
    """Sorted set of the first letter of every name token (PRD §7.1).

    "Sri Krishna V", "Sri Krishna Vijayarajan", "V, Sri K." -> all "ksv".
    """
    if not name:
        return ""
    toks = re.sub(r"[^a-z\s]", " ", strip_accents(name).lower()).split()
    return "".join(sorted({t[0] for t in toks if t}))


def _name_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    return re.sub(r"[^a-z\s]", " ", strip_accents(name).lower()).split()


def _token_match(a: str, b: str) -> bool:
    """Equal, or one is the initial of the other (survives initials)."""
    if a == b:
        return True
    if len(a) == 1 and b.startswith(a):
        return True
    if len(b) == 1 and a.startswith(b):
        return True
    return False


def name_alignment(n1: str | None, n2: str | None) -> str:
    """Return "strong" | "weak" | "none" (order-independent, initial-aware)."""
    t1, t2 = _name_tokens(n1), _name_tokens(n2)
    if not t1 or not t2:
        return "none"
    short, long = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    used = [False] * len(long)
    matched = 0
    for s in short:
        for j, l in enumerate(long):
            if not used[j] and _token_match(s, l):
                used[j] = True
                matched += 1
                break
    if matched == len(short) and matched >= 2:
        return "strong"
    if matched >= 1:
        return "weak"
    return "none"


def _email_set(r: SourceRecord) -> set[str]:
    return {e.value for e in r.emails if e.value}


def _phone_set(r: SourceRecord) -> set[str]:
    return {p.value for p in r.phones if p.value}


def _login(r: SourceRecord) -> str | None:
    # Lower-case so "Sri-Krishna" and "sri-krishna" block/link as one identity.
    if r.github_login and r.github_login.value:
        return str(r.github_login.value).lower()
    return None


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class IdentityResolver:
    def _block_keys(self, r: SourceRecord) -> set[str]:
        keys: set[str] = set()
        for e in _email_set(r):
            keys.add(f"email:{e}")
        login = _login(r)
        if login:
            keys.add(f"login:{login}")
        nbk = name_block_key(r.full_name.value if r.full_name else None)
        if nbk:
            keys.add(f"name:{nbk}")
        return keys

    def _link_score(self, a: SourceRecord, b: SourceRecord) -> float:
        # exact email or github_login -> link outright
        if _email_set(a) & _email_set(b):
            return 1.0
        la, lb = _login(a), _login(b)
        if la and lb and la == lb:
            return 1.0

        alignment = name_alignment(
            a.full_name.value if a.full_name else None,
            b.full_name.value if b.full_name else None,
        )
        corroborated = bool(_phone_set(a) & _phone_set(b))

        if alignment == "strong":
            return NAME_STRONG
        if alignment != "none" and corroborated:
            return NAME_WITH_CORROB
        return INITIAL_MATCH

    def _linked(self, a: SourceRecord, b: SourceRecord) -> bool:
        return self._link_score(a, b) >= LINK_THRESHOLD

    def resolve(self, records: list[SourceRecord]) -> list[list[SourceRecord]]:
        n = len(records)
        uf = _UnionFind(n)

        blocks: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(records):
            for key in self._block_keys(r):
                blocks[key].append(i)

        for idxs in blocks.values():
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    i, j = idxs[a], idxs[b]
                    if uf.find(i) != uf.find(j) and self._linked(records[i], records[j]):
                        uf.union(i, j)

        grouped: dict[int, list[SourceRecord]] = defaultdict(list)
        for i in range(n):
            grouped[uf.find(i)].append(records[i])
        return list(grouped.values())
