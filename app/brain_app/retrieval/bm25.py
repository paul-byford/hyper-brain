"""A small, dependency-free BM25 for the keyword signal.

Rebuilt per query over the domain-filtered candidate set. At small-team corpus
sizes this is cheap, and keeping it self-contained avoids another dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    def __init__(
        self, documents: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.k1 = k1
        self.b = b
        self.documents = [list(d) for d in documents]
        self.n = len(self.documents)
        self.doc_len = [len(d) for d in self.documents]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in self.documents]

        df: Counter[str] = Counter()
        for doc in self.documents:
            df.update(set(doc))
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        scores = [0.0] * self.n
        if not self.avgdl:
            return scores
        for i in range(self.n):
            length = self.doc_len[i] or 1
            tf_i = self.tf[i]
            for term in terms:
                freq = tf_i.get(term)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * length / self.avgdl)
                scores[i] += idf * (freq * (self.k1 + 1)) / denom
        return scores
