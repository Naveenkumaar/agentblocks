"""The agent-definition model — the heart of the platform.

An agent is *pure configuration*: a versioned document of blocks (topics, skills,
connectors, guardrails, knowledge, governance) that the generic engine
interprets. Add a capability by adding a block, not by writing agent-specific
code.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Guardrail(BaseModel):
    """Request/response safety plan applied around every model call."""

    redact_pii: bool = True
    block_injection: bool = True
    allowed_audiences: list[str] = Field(default_factory=lambda: ["user"])


class Skill(BaseModel):
    """A capability the agent can use.

    ``hydrator`` skills read (safe, read-only); ``effector`` skills act and can
    carry a ``risk_tier`` that can require an approval step downstream.
    """

    name: str
    kind: Literal["hydrator", "effector"] = "hydrator"
    connector: str | None = None
    risk_tier: int = 0
    description: str = ""


class Connector(BaseModel):
    """A typed boundary to the outside world (the real trust boundary)."""

    name: str
    kind: Literal["http", "mcp", "sql", "static", "weather"] = "static"
    config: dict[str, Any] = Field(default_factory=dict)


class Topic(BaseModel):
    """A conversational or mission surface the agent exposes."""

    name: str
    mode: Literal["chat", "mission"] = "chat"
    system_prompt: str = ""
    skills: list[str] = Field(default_factory=list)


class Governance(BaseModel):
    """Operational envelope: kill switch, quotas, and tenant data scope."""

    kill_switch: bool = False
    max_turns_per_session: int = 100
    data_scope: Literal["public", "caller_tenant"] = "public"
    approval_required_tier: int = 1   # effector skills at/above this risk_tier need maker-checker approval


class AgentDefinition(BaseModel):
    """A complete, versioned agent expressed entirely as configuration."""

    name: str
    version: int = 1
    description: str = ""
    default_topic: str
    topics: list[Topic]
    skills: list[Skill] = Field(default_factory=list)
    connectors: list[Connector] = Field(default_factory=list)
    guardrails: Guardrail = Field(default_factory=Guardrail)
    governance: Governance = Field(default_factory=Governance)
    knowledge: list[str] = Field(default_factory=list)  # doc ids for RAG

    def topic(self, name: str | None) -> Topic | None:
        target = name or self.default_topic
        return next((t for t in self.topics if t.name == target), None)

    def connector(self, name: str | None) -> Connector | None:
        return next((c for c in self.connectors if c.name == name), None)
