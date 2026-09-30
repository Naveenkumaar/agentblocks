"""HyDE retriever: a hypothetical answer retrieves better than a sparse query."""
from app.knowledge.hyde import HydeRetriever
from app.knowledge.retriever import Retriever

# a corpus where the *answer* wording differs from how a user would ask
CORPUS = {
    "refunds": "Reimbursements for returned purchases are settled within five "
               "business days once the request is approved.",
    "hours": "The support desk operates Monday through Friday, nine to six.",
    "visa": "Short stays under thirty days are exempt from entry permits for "
            "many passport holders.",
}


class _Reply:
    def __init__(self, text): self.text = text


class _FakeModel:
    """Returns a hypothetical answer rich in the target passage's vocabulary."""
    backend = "fake"

    def __init__(self, text): self._text = text

    def generate(self, system, user, context=""): return _Reply(self._text)


class _Stubish:
    """Mimics the offline stub: a generic placeholder with no corpus terms."""
    backend = "stub"

    def generate(self, system, user, context=""):
        return _Reply("(stub) this is a placeholder answer from the offline model.")


def test_hyde_beats_sparse_query():
    r = Retriever(corpus=CORPUS)
    q = "when do I get my money back?"          # zero term overlap with any passage
    # order docs so a zero-score plain query falls back to the WRONG doc (hours)
    order = ["hours", "visa", "refunds"]
    plain = r.retrieve(q, order, top_k=1)[0]
    assert "support desk" in plain              # plain retrieval missed → wrong passage
    # HyDE writes an answer in the target passage's actual vocabulary
    hyp = "Reimbursements for returned purchases are settled within five business days."
    hyde = HydeRetriever(r, _FakeModel(hyp)).retrieve(q, order, top_k=1)[0]
    assert "Reimbursements" in hyde            # HyDE found the right passage
    assert plain != hyde


def test_explain_exposes_the_hypothetical():
    r = Retriever(corpus=CORPUS)
    hr = HydeRetriever(r, _FakeModel("operates Monday through Friday nine to six"))
    res = hr.explain("what time are you open?", list(CORPUS), top_k=1)
    assert "Monday" in res.hypothetical
    assert "support desk" in res.hits[0]


def test_degrades_safely_with_stub_model():
    # with a stub hypothetical (no corpus terms), blending keeps it >= plain query
    r = Retriever(corpus=CORPUS)
    q = "support desk hours"
    plain = r.retrieve(q, list(CORPUS), top_k=1)[0]
    hyde = HydeRetriever(r, _Stubish(), blend_query=True).retrieve(q, list(CORPUS), top_k=1)[0]
    assert hyde == plain                        # never worse than the baseline


def test_model_error_falls_back_to_query():
    class _Boom:
        backend = "boom"
        def generate(self, *a, **k): raise RuntimeError("model down")
    r = Retriever(corpus=CORPUS)
    hr = HydeRetriever(r, _Boom())
    hits = hr.retrieve("support desk hours", list(CORPUS), top_k=1)
    assert hits and "support desk" in hits[0]   # still works
