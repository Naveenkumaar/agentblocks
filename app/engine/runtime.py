"""The turn pipeline — one generic engine for every agent.

    ingress → govern → route → assemble → reason-act → guardrails-out → egress

Each stage appends to a ``trace`` so a turn is fully explainable. No stage knows
anything about a *specific* agent; behaviour comes entirely from the
:class:`AgentDefinition`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.connectors import build_connector
from app.engine.definition import AgentDefinition
from app.engine.model_gateway import get_model
from app.governance import GovernanceError, enforce
from app.guardrails import detect_injection, redact_pii, restore
from app.knowledge import Retriever
from app.memory import MemoryStore


@dataclass
class TurnResult:
    reply: str
    blocked: bool = False
    reason: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


class Engine:
    def __init__(self, memory: MemoryStore | None = None, retriever: Retriever | None = None) -> None:
        self.model = get_model()
        self.memory = memory or MemoryStore()
        self.retriever = retriever or Retriever()

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

        def step(stage: str, **detail: Any) -> None:
            trace.append({"stage": stage, **detail})

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


def _fmt_tools(tool_data: dict[str, Any]) -> str:
    if not tool_data:
        return ""
    return "\n".join(f"[{name}] {value}" for name, value in tool_data.items())
