"""Local cross-encoder reranker (DESIGN.md §5 Phase 3, §13 Decision Log #6).

"Local cross-encoder (ms-marco-MiniLM-L-6-v2)... Free, no external dependency,
~100 MB, CPU-fast at demo K." The model import is deferred inside the function
(not at module load) so importing this module never triggers a download —
rerank/merge.py accepts an injectable `scorer` callable, and the unit test tier
always passes a fake one instead of calling `score_pairs`.
"""

from functools import lru_cache

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache
def _load_model(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def score_pairs(query: str, documents: list[str], model_name: str = DEFAULT_MODEL) -> list[float]:
    """Score each (query, document) pair. Real inference — not used in the unit
    test tier; only exercised once Docker/a real environment can download the
    model, tracked as an integration-test follow-up alongside M2/M3's Docker gap.
    """
    if not documents:
        return []
    model = _load_model(model_name)
    pairs = [(query, doc) for doc in documents]
    return list(model.predict(pairs))
