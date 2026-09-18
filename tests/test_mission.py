"""Mission mode: run → wait (checkpoint) → resume on event → done."""
from pathlib import Path

from app.engine.mission import MissionRunner
from app.engine.registry import Registry

AGENTS = Path(__file__).parents[1] / "agents"


def _agent():
    r = Registry()
    return r.load_file(AGENTS / "onboarding-mission.json")


def test_starts_runs_first_step_then_waits():
    agent = _agent()
    run = MissionRunner().start(agent)
    assert run.status == "waiting"
    assert run.waiting_for == "kyc_passed"
    assert [x["step"] for x in run.results] == ["send-welcome"]   # step before the wait ran
    assert run.results[0]["ok"]


def test_wrong_event_keeps_waiting():
    agent = _agent()
    runner = MissionRunner()
    run = runner.start(agent)
    runner.resume(run, "something_else", agent)
    assert run.status == "waiting" and run.waiting_for == "kyc_passed"


def test_correct_event_resumes_to_completion():
    agent = _agent()
    runner = MissionRunner()
    run = runner.start(agent)
    runner.resume(run, "kyc_passed", agent)
    assert run.status == "done"
    assert [x["step"] for x in run.results] == ["send-welcome", "provision-account"]
    assert run.results[-1]["data"] == {"provisioned": True}


def test_checkpoint_is_the_cursor_and_results():
    # a waiting run carries enough state to resume: cursor + results + waiting_for
    run = MissionRunner().start(_agent())
    assert run.cursor == 1                       # parked on the wait step
    assert run.as_dict()["waiting_for"] == "kyc_passed"


def test_resume_of_a_done_mission_is_ignored():
    agent = _agent()
    runner = MissionRunner()
    run = runner.start(agent)
    runner.resume(run, "kyc_passed", agent)      # -> done
    runner.resume(run, "kyc_passed", agent)      # no-op
    assert run.status == "done"
    assert any("ignored_event" in t for t in run.trace)
