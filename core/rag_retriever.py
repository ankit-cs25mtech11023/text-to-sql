"""Phase 5-B RAG retriever (few-shot side).

Embeds the user question once and retrieves the most similar solved examples from
the disjoint pool (`evaluation/rag_qsql_store.json`). Schema-table retrieval is
delegated to an optional SchemaIndexer (wired in a later step); until then
`retrieve_tables` returns [].

Design (RAG_plan.md §5.2):
- The dense vector embeds the QUESTION TEXT ONLY — symmetric with the query. Pool
  SQL/structure is never embedded (that asymmetry hurts); it enters via the hybrid
  lexical (BM25) signal and the optional category rerank instead.
- Retrieval is deterministic: exact inner-product search over L2-normalized
  embeddings (== faiss.IndexFlatIP), fixed seed, stable tie-break by ascending id.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from config.settings import Settings

_RRF_C = 60  # standard reciprocal-rank-fusion damping constant
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# Ordered keyword heuristic for the PREDICTED question category (never the gold
# label — see RAG_plan §3.5). Used only when rag_category_weight > 0. First match
# wins, so the most specific patterns are listed first.
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("subquery", ("above the average", "below the average", "above the overall",
                  "more than the average", "than the average")),
    ("having", ("more than", "at least", "fewer than", "above ")),
    ("decode", ("financial year", "month name", "per month", "by month",
                "labelled by year", "year name", "per quarter", "each quarter")),
    ("ranking", ("top ", "highest", "lowest", "most ", "which ", "rank")),
    ("grouping", ("for each", "per each", "by each", "each ")),
    ("quirk", ("travel distance", "invoice value", "timestamp", "refresh date",
               "filing date", "in km")),
    ("filtering", ("how many", "above ", "over ", "with ", "filed in")),
    ("domain_specific", ("intra-state", "inter-state", "tds", "cess", "itc", "igst")),
]


def _predict_category(question: str) -> str:
    q = question.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in q for kw in keywords):
            return category
    return "aggregation"


class _SchemaIndexerLike(Protocol):
    def retrieve_tables(self, question: str, k: int) -> list[str]: ...


class RAGRetriever:
    def __init__(self, settings: Settings, schema_indexer: _SchemaIndexerLike | None = None) -> None:
        self._settings = settings
        self._schema_indexer = schema_indexer

        np.random.seed(settings.rag_embed_seed)

        self._pool: list[dict] = json.loads(Path(settings.qsql_store_path).read_text())
        self._model = SentenceTransformer(settings.embed_model)

        questions = [p["question"] for p in self._pool]
        emb = self._model.encode(
            questions, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        self._index = faiss.IndexFlatIP(emb.shape[1])
        self._index.add(emb)
        self._bm25 = BM25Okapi([_tokenize(q) for q in questions])

    def _embed_one(self, question: str) -> np.ndarray:
        return self._model.encode(
            [question], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")

    def _dense_scores(self, question: str) -> np.ndarray:
        qv = self._embed_one(question)
        sims, idxs = self._index.search(qv, len(self._pool))  # full ranking
        scores = np.empty(len(self._pool), dtype="float32")
        scores[idxs[0]] = sims[0]
        return scores

    def _order_by(self, score_fn) -> list[int]:
        """Stable deterministic order: descending score, ties broken by ascending pool id."""
        return sorted(range(len(self._pool)), key=lambda i: (-score_fn(i), self._pool[i]["id"]))

    def _rank_indices(self, question: str) -> list[int]:
        dense = self._dense_scores(question)
        if self._settings.rag_retrieval_mode == "semantic":
            ranked = self._order_by(lambda i: float(dense[i]))
        else:
            ranked = self._rank_hybrid(question, dense)
        if self._settings.rag_category_weight > 0:
            ranked = self._rerank_by_category(question, ranked)
        return ranked

    def _rank_hybrid(self, question: str, dense: np.ndarray) -> list[int]:
        bm25 = self._bm25.get_scores(_tokenize(question))
        dense_rank = {i: r for r, i in enumerate(self._order_by(lambda i: float(dense[i])))}
        bm25_rank = {i: r for r, i in enumerate(self._order_by(lambda i: float(bm25[i])))}

        def rrf(i: int) -> float:
            return 1.0 / (_RRF_C + dense_rank[i]) + 1.0 / (_RRF_C + bm25_rank[i])

        return self._order_by(rrf)

    def _rerank_by_category(self, question: str, ranked: list[int]) -> list[int]:
        predicted = _predict_category(question)
        n = len(ranked)
        pos = {idx: r for r, idx in enumerate(ranked)}
        w = self._settings.rag_category_weight

        def final(i: int) -> float:
            retrieval = 1.0 - pos[i] / n
            match = 1.0 if self._pool[i]["category"] == predicted else 0.0
            return (1.0 - w) * retrieval + w * match

        return self._order_by(final)

    def retrieve_fewshots(self, question: str, k: int | None = None) -> list[dict]:
        k = k or self._settings.rag_top_k_fewshots
        return [self._pool[i] for i in self._rank_indices(question)[:k]]

    def retrieve_tables(self, question: str, k: int | None = None) -> list[str]:
        if self._schema_indexer is None:
            return []
        return self._schema_indexer.retrieve_tables(question, k or self._settings.rag_top_k_tables)

    def retrieve(self, question: str) -> dict:
        return {
            "tables": self.retrieve_tables(question),
            "fewshots": self.retrieve_fewshots(question),
        }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config.settings import get_settings

    r = RAGRetriever(get_settings())
    for q in [
        "What is the total CGST payable for each financial year, labelled by year?",
        "How many e-way bills were cancelled?",
        "Which deductor withheld the most TDS?",
    ]:
        print(f"\nQ: {q}")
        for s in r.retrieve_fewshots(q):
            print(f"  #{s['id']} [{s['category']}/{s['module']}] {s['question']}")
