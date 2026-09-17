"""The turn pipeline — one generic engine for every agent.

    ingress → govern → guardrails-in → route → assemble → reason-act
            → effect (maker-checker) → guardrails-out → egress

Each stage appends to a ``trace`` so a turn is fully explainable. No stage knows
anything about a *specific* agent; behaviour comes entirely from the
:class:`AgentDefinition`. A high-risk effector at the ``effect`` stage suspends
the turn for a second approver instead of executing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.connectors import build_connector
from app.engine.definition import AgentDefinition
from app.engine.model_gateway import get_model
from app.governance import ApprovalStore, GovernanceError, enforce
from app.guardrails import detect_injection, redact_pii, restore
from app.knowledge import Retriever
from app.memory import MemoryStore


@dataclass
class TurnResult:
    reply: str
    blocked: bool = False
    reason: str | None = None
    suspended: bool = False
    approval_id: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


class Engine:
    def __init__(self, memory: MemoryStore | None = None, retriever: Retriever | None = None,
                 approvals: ApprovalStore | None = None) -> None:
        self.model = get_model()
        self.memory = memory or MemoryStore()
        self.retriever = retriever or Retriever()
        self.approvals = approvals or ApprovalStore()

    def run_turn(
        self,
        agent: AgentDefinition,
        message: str,
        session_id: str = "default",
        topic_name: str | None = None,
        audience: str = "user",
        scope: dict[str, Any] | None = None,
    ) -> TurnResult:
        trace: list[dict[str, Any]] = []
        last = [time.perf_counter()]   # per-stage timer; ms = time since previous stage

        def step(stage: str, **detail: Any) -> None:
            now = time.perf_counter()
            ms = round((now - last[0]) * 1000, 2)
            last[0] = now
            trace.append({"stage": stage, "ms": ms, **detail})

        # 1. ingress
        step("ingress", chars=len(message), session=session_id)

        # 2. govern
        try:
            enforce(agent.governance, self.memory.turn_count(session_id))
        except GovernanceError as exc:
            step("govern", refused=str(exc))
            return TurnResult(reply="Sorry, I can't take that turn right now.",
                              blocked=True, reason=str(exc), trace=trace)
        step("govern", ok=True)

        # 3. guardrails-in: injection defense + PII tokenize
        is_injection, signal = detect_injection(message)
        if is_injection and agent.guardrails.block_injection:
            step("guardrails-in", blocked_injection=signal)
            return TurnResult(reply="That request can't be processed.",
                              blocked=True, reason=f"injection:{signal}", trace=trace)
        safe_message, vault = (redact_pii(message) if agent.guardrails.redact_pii else (message, {}))
        step("guardrails-in", pii_tokens=len(vault), injection=is_injection)

        # 4. route to a topic
        topic = agent.topic(topic_name)
        if topic is None:
            step("route", error="no topic")
            return TurnResult(reply="No topic is configured for this agent.",
                              blocked=True, reason="no-topic", trace=trace)
        step("route", topic=topic.name, mode=topic.mode)

        # 5. assemble context: memory + knowledge + skills(hydrators)
        history = self.memory.context(session_id)
        knowledge = self.retriever.retrieve(safe_message, agent.knowledge) if agent.knowledge else []
        tool_data = self._run_hydrators(agent, topic, safe_message, scope, step)
        context = "\n".join(
            filter(None, [history, "\n".join(knowledge), _fmt_tools(tool_data)])
        )
        step("assemble", history_turns=self.memory.turn_count(session_id),
             knowledge=len(knowledge), tools=len(tool_data))

        # 6. reason-act: the model call
        reply = self.model.generate(topic.system_prompt, safe_message, context)
        step("reason-act", backend=reply.backend, chars=len(reply.text))

        # 6b. effect: run effector skills; suspend high-risk ones for approval
        appr = self._run_effectors(agent, topic, safe_message, audience, step)
        if appr is not None:
            self.memory.append(session_id, "user", message)
            return TurnResult(
                reply=f"The action '{appr.skill}' needs a second approver before it "
                      f"runs. Created approval {appr.id}.",
                suspended=True, approval_id=appr.id, trace=trace)

        # 7. guardrails-out: re-mask per audience
        out = reply.text
        if vault and audience in agent.guardrails.allowed_audiences:
            out = restore(out, vault)
            step("guardrails-out", audience=audience, revealed=True)
        else:
            step("guardrails-out", audience=audience, revealed=False)

        # 8. egress
        self.memory.append(session_id, "user", message)
        self.memory.append(session_id, "assistant", out)
        step("egress", chars=len(out))
        return TurnResult(reply=out, trace=trace)

    # ------------------------------------------------------------------
    def run_turn_stream(self, agent: AgentDefinition, message: str, session_id: str = "default",
                        topic_name: str | None = None, audience: str = "user",
                        scope: dict[str, Any] | None = None):
        """Same pipeline as :meth:`run_turn`, but yields events as they happen:
        ``{"type": "token", "text": ...}`` during reason-act, then a final
        ``{"type": "done", "reply", "trace", ...}``. Early exits (govern/injection/
        no-topic) yield only a ``done`` event.
        """
        trace: list[dict[str, Any]] = []
        last = [time.perf_counter()]

        def step(stage: str, **detail: Any) -> None:
            now = time.perf_counter()
            trace.append({"stage": stage, "ms": round((now - last[0]) * 1000, 2), **detail})
            last[0] = now

        def done(reply: str, **kw: Any) -> dict[str, Any]:
            return {"type": "done", "reply": reply, "trace": trace, **kw}

        step("ingress", chars=len(message), session=session_id)
        try:
            enforce(agent.governance, self.memory.turn_count(session_id))
        except GovernanceError as exc:
            step("govern", refused=str(exc))
            yield done("Sorry, I can't take that turn right now.", blocked=True, reason=str(exc))
            return
        step("govern", ok=True)

        is_injection, signal = detect_injection(message)
        if is_injection and agent.guardrails.block_injection:
            step("guardrails-in", blocked_injection=signal)
            yield done("That request can't be processed.", blocked=True, reason=f"injection:{signal}")
            return
        safe_message, vault = (redact_pii(message) if agent.guardrails.redact_pii else (message, {}))
        step("guardrails-in", pii_tokens=len(vault), injection=is_injection)

        topic = agent.topic(topic_name)
        if topic is None:
            step("route", error="no topic")
            yield done("No topic is configured for this agent.", blocked=True, reason="no-topic")
            return
        step("route", topic=topic.name, mode=topic.mode)

        history = self.memory.context(session_id)
        knowledge = self.retriever.retrieve(safe_message, agent.knowledge) if agent.knowledge else []
        tool_data = self._run_hydrators(agent, topic, safe_message, scope, step)
        context = "\n".join(filter(None, [history, "\n".join(knowledge), _fmt_tools(tool_data)]))
        step("assemble", history_turns=self.memory.turn_count(session_id),
             knowledge=len(knowledge), tools=len(tool_data))

        chunks: list[str] = []
        for tok in self.model.generate_stream(topic.system_prompt, safe_message, context):
            chunks.append(tok)
            yield {"type": "token", "text": tok}
        reply_text = "".join(chunks)
        step("reason-act", backend=getattr(self.model, "backend", "?"), chars=len(reply_text))

        appr = self._run_effectors(agent, topic, safe_message, audience, step)
        if appr is not None:
            self.memory.append(session_id, "user", message)
            yield done(f"The action '{appr.skill}' needs a second approver before it runs. "
                       f"Created approval {appr.id}.", suspended=True, approval_id=appr.id)
            return

        out = reply_text
        if vault and audience in agent.guardrails.allowed_audiences:
            out = restore(out, vault)
            step("guardrails-out", audience=audience, revealed=True)
        else:
            step("guardrails-out", audience=audience, revealed=False)
        self.memory.append(session_id, "user", message)
        self.memory.append(session_id, "assistant", out)
        step("egress", chars=len(out))
        yield done(out)

    # ------------------------------------------------------------------
    def _run_hydrators(self, agent, topic, message, scope, step) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for skill_name in topic.skills:
            skill = next((s for s in agent.skills if s.name == skill_name), None)
            if skill is None or skill.kind != "hydrator":
                continue
            spec = agent.connector(skill.connector)
            if spec is None:
                continue
            connector = build_connector(spec)
            res = connector.invoke({"query": message}, scope=scope)
            results[skill.name] = res.data
            step("hydrate", skill=skill.name, connector=spec.name, ok=res.ok)
        return results

    def _run_effectors(self, agent, topic, message, maker, step):
        """Run effector skills. A high-risk one (risk_tier >= the agent's
        approval_required_tier) is not executed — it creates a pending approval
        and the turn suspends. Returns that Approval, or None if nothing suspended.
        """
        tier = agent.governance.approval_required_tier
        for skill_name in topic.skills:
            skill = next((s for s in agent.skills if s.name == skill_name), None)
            if skill is None or skill.kind != "effector":
                continue
            if skill.risk_tier >= tier:
                appr = self.approvals.create(agent.name, skill.name, maker,
                                             {"query": message})
                step("effect", skill=skill.name, risk_tier=skill.risk_tier,
                     suspended=appr.id)
                return appr
            spec = agent.connector(skill.connector)
            res = build_connector(spec).invoke({"query": message}) if spec else None
            step("effect", skill=skill.name, risk_tier=skill.risk_tier,
                 executed=True, ok=(res.ok if res else None))
        return None

    def execute_approved(self, appr, agent: AgentDefinition):
        """Run the action behind an approved Approval (called after a checker
        approves). Resolves the effector's connector and invokes it."""
        skill = next((s for s in agent.skills if s.name == appr.skill), None)
        spec = agent.connector(skill.connector) if skill else None
        res = build_connector(spec).invoke(appr.params) if spec else None
        appr.result = res.data if res else {"note": "no connector bound"}
        appr.status = "executed"
        return appr


def _fmt_tools(tool_data: dict[str, Any]) -> str:
    if not tool_data:
        return ""
    return "\n".join(f"[{name}] {value}" for name, value in tool_data.items())
