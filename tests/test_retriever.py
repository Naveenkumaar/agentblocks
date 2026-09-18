"""TF-IDF cosine retriever: relevant docs rank first, deterministically."""
from app.knowledge import Retriever

CORPUS = {
    "visa": "Most short visits under 30 days are visa-exempt for many passports.",
    "weather": "Pack layers for mountain regions; weather changes quickly at altitude.",
    "refunds": "Refunds are processed within five business days of approval.",
}


def test_ranks_the_relevant_doc_first():
    r = Retriever(CORPUS)
    ranked = r.scores("do I need a visa for a short visit?", list(CORPUS))
    assert ranked[0][0] == "visa"
    assert ranked[0][1] > 0

    weather = r.scores("what should I pack for cold mountain weather?", list(CORPUS))
    assert weather[0][0] == "weather"


def test_retrieve_returns_texts_top_k():
    r = Retriever(CORPUS)
    hits = r.retrieve("visa exemption for passports", list(CORPUS), top_k=1)
    assert len(hits) == 1
    assert "visa-exempt" in hits[0]


def test_deterministic_scores():
    r = Retriever(CORPUS)
    a = r.scores("refund approval time", list(CORPUS))
    b = r.scores("refund approval time", list(CORPUS))
    assert a == b                       # identical, run to run


def test_no_match_falls_back_but_does_not_crash():
    r = Retriever(CORPUS)
    hits = r.retrieve("xyzzy quux", list(CORPUS), top_k=2)
    assert len(hits) == 2               # falls back to first candidates, never empty


def test_only_scores_candidate_docs():
    r = Retriever(CORPUS)
    ranked = r.scores("visa", ["visa", "refunds"])
    assert {d for d, _ in ranked} == {"visa", "refunds"}   # 'weather' excluded
