"""BM25 keyword scoring in plain Python, the same on SQLite and PostgreSQL (Week 5 Step 3).

Standard Okapi BM25 (k1 = 1.2, b = 0.75) with the smoothed idf log(1 + (N - df + 0.5) / (df + 0.5)), which
is never negative. Tokens are lowercase words and numbers ("15", "20", "48"), because exact amounts and day
counts are what keyword search is for here.

`normalised` divides a chunk's score by the query's maximum possible score (the sum over its terms of
idf × (k1 + 1), the limit as term frequency grows). A query made of words the corpus never uses therefore
scores near 0 everywhere, instead of its best chunk always looking like a perfect match.
"""

import math
import re
from collections import Counter

K1, B = 1.2, 0.75
STOP = frozenset(
    """a an and are as at be by can do does for from has have how i if in is it its me my of on or
our so that the their them then there these this to was we what when where which who will with you your""".split()
)


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class BM25:
    def __init__(self, documents: list[str]):
        self.docs = [Counter(tokens(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.n = len(documents)
        self.avg = (sum(self.lengths) / self.n) if self.n else 0.0
        self.df = Counter(t for c in self.docs for t in c)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        terms = tokens(query)
        out = []
        for counts, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in terms:
                tf = counts.get(t, 0)
                if tf:
                    s += self.idf(t) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / (self.avg or 1)))
            out.append(s)
        return out

    def max_possible(self, query: str) -> float:
        return sum(self.idf(t) * (K1 + 1) for t in tokens(query))

    def normalised(self, query: str) -> list[float]:
        top = self.max_possible(query)
        return [s / top if top else 0.0 for s in self.scores(query)]


def rrf(*rankings: list[int], k: int) -> list[float]:
    """Reciprocal rank fusion. Each ranking lists item indexes best first; returns a fused score per item."""
    n = max((len(r) for r in rankings), default=0)
    fused = [0.0] * n
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] += 1.0 / (k + rank)
    return fused
