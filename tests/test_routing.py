"""Pluggable router backends: overlap (default), vector (TF-IDF), embedding."""
from app.engine.orchestrator import Orchestrator
from app.engine.registry import Registry
from app.engine.routing import (
    EmbeddingRouter, OverlapRouter, VectorRouter, get_router,
)

PROFILES = {
    "faq-helper": "faq helper answers questions about refunds hours and policy",
    "trip-planner": "trip planner books travel weather itinerary destinations",
    "mcp-tools-agent": "calls mcp tools echo add upper over json-rpc",
}


def test_get_router_selects_backend():
    assert isinstance(get_router("overlap"), OverlapRouter)
    assert isinstance(get_router("tfidf"), VectorRouter)
    assert isinstance(get_router("embedding"), EmbeddingRouter)
    assert isinstance(get_router(), OverlapRouter)          # default


def test_overlap_and_vector_agree_on_a_clear_match():
    task = "what is the refund policy"
    assert OverlapRouter().rank(task, PROFILES)[0][0] == "faq-helper"
    assert VectorRouter().rank(task, PROFILES)[0][0] == "faq-helper"


def test_vector_weights_distinctive_terms():
    # "weather" is distinctive to trip-planner → high cosine, positive score
    ranked = VectorRouter().rank("check the weather for my travel", PROFILES)
    assert ranked and ranked[0][0] == "trip-planner"
    assert ranked[0][1] > 0                                 # a cosine score


def test_vector_falls_back_when_no_overlap():
    # a task sharing no tokens → TF-IDF is all-zero → falls back to overlap (also empty)
    assert VectorRouter().rank("zzzz qqqq", PROFILES) == []


def test_embedding_router_falls_back_offline():
    # no Ollama running → EmbeddingRouter degrades to its VectorRouter fallback
    ranked = EmbeddingRouter().rank("what is the refund policy", PROFILES)
    assert ranked and ranked[0][0] == "faq-helper"


def test_orchestrator_accepts_a_router_and_still_routes():
    r = Registry()
    from pathlib import Path
    A = Path(__file__).parents[1] / "agents"
    for f in ["faq-helper.json", "trip-planner.json"]:
        r.load_file(A / f)
    res = Orchestrator(r, router=VectorRouter()).run("check the refund policy")
    assert res.steps[0].agent == "faq-helper" and res.steps[0].confidence == "high"
