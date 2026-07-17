"""Phase 5-B schema indexer — M-Schema per table -> FAISS (schema-retrieval side).

Embeds one vector per table (its M-Schema block) so a question can retrieve only the
relevant tables instead of the full ~26.5K-token static schema dump. Implements the
`_SchemaIndexerLike` protocol expected by RAGRetriever (retrieve_tables(q, k) -> blocks).

Deterministic (RAG_plan §5.2): exact inner-product search over L2-normalized embeddings
(== faiss.IndexFlatIP), stable tie-break by ascending table name. The core tables (3
module MAINs + 4 common masters) are always injected when
settings.rag_always_include_core_tables (ablation toggle, §6/§9), and every selected
table pulls its FK ancestors in (closure) so bridge tables are never missing.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config.settings import Settings
from core.schema_extractor import SchemaExtractor

# Always injected under always-core (RAG_plan §7): the 3 module MAIN tables plus the
# 4 common masters. Masters are dimension/hub tables whose content is semantically
# distant from question text ("division", "FY 2024-25", taxpayer names never embed
# near mst_state_jurisdiction_code etc.) so top-k retrieval structurally misses them
# — the v2 coverage-failure class (#50/61/62/75/162).
_CORE_TABLES = (
    "public.tbl_ewb_parta_ewb",
    "public.tbl_gst_rtn_r3b",
    "public.tbl_gst_rtn_r7",
    "common.t_all_delers_api_v_t",
    "common.mst_state_jurisdiction_code",
    "common.mst_fy_years_t",
    "common.mst_3bd_months_t",
)


class SchemaIndexer:
    def __init__(
        self,
        extractor: SchemaExtractor,
        settings: Settings,
        model: SentenceTransformer | None = None,
    ) -> None:
        self._extractor = extractor
        self._settings = settings
        # model may be shared with RAGRetriever so bge-large loads only once.
        self.model = model or SentenceTransformer(settings.embed_model)
        self._dir = Path(settings.rag_index_dir)
        self._faiss_path = self._dir / "schema.faiss"
        self._meta_path = self._dir / "tables.pkl"
        self._names: list[str] = []
        self._blocks: dict[str, str] = {}
        self._parents: dict[str, list[str]] = {}
        self._index: faiss.Index | None = None

    def build_index(self) -> None:
        self._blocks = self._extractor.get_table_blocks()
        self._parents = self._extractor.get_fk_parents()
        self._names = sorted(self._blocks)  # deterministic vector order
        texts = [self._blocks[n] for n in self._names]
        emb = self.model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)
        self._index = index
        self._dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self._faiss_path))
        with self._meta_path.open("wb") as f:
            pickle.dump(
                {"names": self._names, "blocks": self._blocks, "parents": self._parents}
            , f)

    def load(self) -> None:
        self._index = faiss.read_index(str(self._faiss_path))
        with self._meta_path.open("rb") as f:
            meta = pickle.load(f)
        self._names = meta["names"]
        self._blocks = meta["blocks"]
        self._parents = meta.get("parents") or {}
        if not self._parents:  # pre-closure index on disk — rebuild with parents map
            self.build_index()

    def load_or_build(self) -> None:
        if self._faiss_path.exists() and self._meta_path.exists():
            self.load()
        else:
            self.build_index()

    def retrieve_tables(self, question: str, k: int) -> list[str]:
        if self._index is None:
            self.load_or_build()
        qv = self.model.encode(
            [question], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        sims, idxs = self._index.search(qv, len(self._names))
        scores = np.empty(len(self._names), dtype="float32")
        scores[idxs[0]] = sims[0]
        order = sorted(range(len(self._names)), key=lambda i: (-float(scores[i]), self._names[i]))
        top = [self._names[i] for i in order[:k]]
        if self._settings.rag_always_include_core_tables:
            core = [c for c in _CORE_TABLES if c in self._blocks]
            selected = list(dict.fromkeys(core + top))  # core first, dedup, preserve order
        else:
            selected = top
        return [self._blocks[n] for n in self._fk_closure(selected)]

    def _fk_closure(self, names: list[str]) -> list[str]:
        """Inject each selected table's FK ancestors before it. Bridge tables
        (tbl_gst_rtn_r3b_sup_details etc.) are semantically bland so retrieval
        misses them — the v2 bridge-failure class (#61/66/139): without the
        parent in the prompt the LLM hallucinates the join key."""
        out: list[str] = []

        def add(n: str, seen: set[str]) -> None:
            if n in out or n in seen:
                return
            seen.add(n)
            for p in self._parents.get(n, []):
                if p in self._blocks:
                    add(p, seen)
            out.append(n)

        for n in names:
            add(n, set())
        return out


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config.settings import get_settings
    from database.connection import get_engine

    s = get_settings()
    eng = get_engine(s.database_url, read_only=True)
    ext = SchemaExtractor(eng, s.descriptions_path)
    idx = SchemaIndexer(ext, s)
    idx.build_index()
    print(f"built schema index: {len(idx._names)} tables -> {idx._faiss_path}")
    for q in [
        "What is the total CGST payable for each financial year, labelled by year?",
        "Which deductor withheld the most TDS?",
        "How many e-way bills were cancelled?",
    ]:
        blocks = idx.retrieve_tables(q, s.rag_top_k_tables)
        heads = [b.split("\n", 1)[0].replace("Table: ", "")[:48] for b in blocks]
        print(f"\nQ: {q}")
        for h in heads:
            print(f"  - {h}")
