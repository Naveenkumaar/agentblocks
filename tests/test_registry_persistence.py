"""A SQLite-backed registry survives restart (versions + active pointer)."""
import json
import os
import tempfile
from pathlib import Path

from app.engine.registry import Registry

AGENTS = Path(__file__).parents[1] / "agents"
FAQ = json.loads((AGENTS / "faq-helper.json").read_text())


def _db():
    return os.path.join(tempfile.mkdtemp(), "registry.db")


def test_versions_persist_across_instances():
    db = _db()
    Registry(db).load_file(AGENTS / "faq-helper.json")     # write, drop instance
    reopened = Registry(db)                                 # fresh "process"
    assert "faq-helper" in reopened.names()
    assert reopened.get("faq-helper").description == FAQ["description"]


def test_active_pointer_persists():
    db = _db()
    r = Registry(db)
    r.load_file(AGENTS / "faq-helper.json")
    r.activate("faq-helper", 1, gate=lambda d: {"passed": True})
    assert Registry(db).is_active("faq-helper")


def test_immutability_still_enforced_with_db():
    db = _db()
    r = Registry(db)
    r.load_file(AGENTS / "faq-helper.json")
    try:
        r.load_file(AGENTS / "faq-helper.json")
    except ValueError:
        return
    raise AssertionError("re-adding an existing version must raise")


def test_in_memory_default_has_no_db():
    assert Registry()._db is None
