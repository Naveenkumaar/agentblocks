<div align="center">

# ▣ agentblocks

**Agents as versioned configuration — one generic engine.**

Define any number of AI agents entirely as **versioned JSON documents of blocks**
(topics · skills · connectors · guardrails · knowledge · memory · governance),
interpreted by a single definition-driven engine. Nothing about any specific
agent lives in code.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](app/main.py)
[![Pydantic](https://img.shields.io/badge/Config-Pydantic_v2-E92063)](app/engine/definition.py)
[![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC)](tests/)
[![Runs offline](https://img.shields.io/badge/model-offline_stub_by_default-6E56CF)](app/engine/model_gateway.py)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

> **Clean-room project.** Every line here is written from scratch on a neutral
> domain (support FAQ + travel), using only public APIs and synthetic data. It
> demonstrates general agent-engineering patterns — it is not derived from, and
> contains no code, schema, or data from, any employer system.

---

## Table of contents

- [Why](#why)
- [Security posture](#security-posture)
- [Quick start](#quick-start)
- [How a turn flows](#how-a-turn-flows)
- [The agent-definition model](#the-agent-definition-model)
- [Seeded agents](#seeded-agents)
- [The eval gate](#the-eval-gate)
- [Repository map](#repository-map)
- [Roadmap](#roadmap)

> **Full design write-up:** [ARCHITECTURE.md](ARCHITECTURE.md) — the two planes, the
> eight-stage turn pipeline, the connector trust boundary, and the design decisions
> behind each, all mapped to the code.

---

## Why

Most agent codebases hard-code one agent. Adding a second means copy-pasting a
pipeline. **agentblocks** flips that: the *pipeline* is generic and the *agent*
is data. You add a capability by adding a block to a JSON definition, version it,
and it can't go live until it passes its eval gate. That is the difference
between a demo and a platform.

---

## Security posture

Guardrails redact synthetic PII and refuse obvious prompt-injection at the edge,
but the enforcement that matters happens below the model: a
[connector](app/connectors/base.py) merges the caller's resolved scope into
every outbound call, so an injected request cannot widen its own access. The
[adversarial suite](evals/adversarial.yaml) gates activation on exactly this.

---

## Quick start

Runs **offline with no API key** — the default model backend is a deterministic stub.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# validate the seeded agents
.venv/bin/python scripts/seed.py

# run the eval gate (golden + adversarial) — exits non-zero on failure
.venv/bin/python evals/run_eval.py

# run the tests
.venv/bin/python -m pytest -q

# start the platform + operator console
.venv/bin/python -m uvicorn app.main:app --port 8080
#  → open http://localhost:8080/
```

Want a real model? `export MODEL_BACKEND=ollama` (local, free) — no code changes.

Try a turn from the console, or:

```bash
curl -s localhost:8080/v1/agents/faq-helper/turns \
  -H 'content-type: application/json' \
  -d '{"message":"What are your support hours?"}' | python3 -m json.tool
```

---

## How a turn flows

One generic pipeline, fully traced, for every agent:

```
ingress → govern → guardrails-in → route → assemble → reason-act → guardrails-out → egress
             │          │            │        │            │              │
        kill-switch  injection    pick a   memory +     model call    re-mask per
        + quotas     + PII tok.   topic    knowledge +                audience
                                           hydrator tools
```

Every stage appends to a `trace`, so each answer is explainable end to end (see it live in the console).

---

## The agent-definition model

An agent is a [`AgentDefinition`](app/engine/definition.py) — a versioned document of blocks:

| Block | Purpose |
|-------|---------|
| `topics` | chat / mission surfaces, each with a system prompt + allowed skills |
| `skills` | `hydrator` (read) or `effector` (act, with a `risk_tier`) capabilities |
| `connectors` | typed boundaries to the world — `http` / `mcp` / `sql` / `static` / `weather` / `agent` (delegate to another agent) |
| `guardrails` | PII tokenize/restore + injection defense, per-audience reveal |
| `knowledge` | doc ids for RAG retrieval |
| `memory` | bounded session history |
| `governance` | kill switch · session quotas · `data_scope` |

Versions are **immutable**; a version activates only through the eval gate.

---

## Seeded agents

| Agent | What it demonstrates |
|-------|----------------------|
| [`faq-helper`](agents/faq-helper.json) | the minimal agent — one topic, knowledge only, everything else inherited |
| [`trip-planner`](agents/trip-planner.json) | multi-tool — a **live weather tool** (Open-Meteo, no API key) over a connector + RAG over travel docs |
| [`supervisor-router`](agents/supervisor-router.json) | supervisor that routes across specialists discovered from the registry |
| [`mc-verify-agent`](agents/mc-verify-agent.json) | maker-checker — a tier-2 effector suspends for a second approver (`checker != maker`) |
| [`mcp-tools-agent`](agents/mcp-tools-agent.json) | calls a **real MCP tool server** (JSON-RPC over stdio) via the `mcp` connector |
| [`concierge-agent`](agents/concierge-agent.json) | **agents calling agents** — delegates to `faq-helper` through an `agent` connector and folds its reply in |
| [`onboarding-mission`](agents/onboarding-mission.json) | **mission mode** — run a step, `wait:` for an event, then resume to completion |

---

## The eval gate

Two suites in [`evals/`](evals/):

- **`golden.yaml`** — normal requests that must be answered.
- **`adversarial.yaml`** — injection / scope-escape attempts that must be refused.

[`registry.activate()`](app/engine/registry.py) refuses to make a version live
unless it clears the gate — the single most important control in the platform,
and a CI check (`python evals/run_eval.py`).

---

## Repository map

```
app/
  engine/       definition · registry (+ activation gate) · runtime (turn pipeline) · orchestrator (autonomous) · routing (pluggable) · mission · model_gateway
  guardrails/   redact (PII tokenize/restore) · injection (deny-list)
  connectors/   base (scope boundary) · http · mcp (real JSON-RPC server) · static · weather (live Open-Meteo) · agent (delegate to another agent)
  knowledge/    dependency-free TF-IDF cosine retriever (swap for embeddings)
  memory/       bounded session store
  governance/   kill switch · quotas
  mcp/          a real MCP tool server (JSON-RPC over stdio) + demo tools
  ui/           console.html — self-contained operator console (no build step)
  main.py       FastAPI: control plane + runtime plane + console
agents/         the 6 seeded JSON definitions
evals/          golden + adversarial suites + gate runner
tests/          pytest (engine · guardrails · connectors · approvals · streaming · mcp)
ARCHITECTURE.md the full design write-up, mapped to the code
```

---

## Roadmap

- [x] A real, key-free external tool wired end to end (`weather` → Open-Meteo)
- [x] `effector` skills with **maker-checker** approval for high-risk actions
- [x] Per-stage **latency** in every trace, surfaced in the console
- [x] **Streaming turns** — token-by-token over SSE, rendered live in the console
- [x] Real **MCP** tool server (JSON-RPC over stdio) behind the `mcp` connector
- [x] Persist versions + active pointer (SQLite; `AGENTBLOCKS_DB=agents.db`) — Postgres/pgvector is the production target
- [x] Vector-search knowledge store — **TF-IDF cosine** retriever (dependency-free); embeddings/pgvector next
- [x] **Autonomous orchestration** — **LLM-planned** goal decomposition (rule-based fallback), route each sub-task to the best specialist agent (no hand-authored membership) via a **pluggable router** (`ROUTER_BACKEND`: token-overlap / TF-IDF vector / embedding, each with a deterministic fallback) with **explainable scores + a clarify-don't-guess** safety flag on weak/ambiguous matches, **chain dependent sub-tasks over a dependency DAG** (the planner emits explicit `deps` edges — catching dependencies even with no back-reference — and each step gets only its referenced results as context), **preview/edit the plan before it runs** (`POST /v1/plan` → inspect edges + routing; `POST /v1/orchestrate` runs a caller-edited plan verbatim) with a **topological schedule** (`layers`) showing which steps are independent, then **synthesize one final answer**
- [x] **Agents calling agents** — an `agent` connector runs a sub-turn on another agent as a tool (`concierge-agent` → `faq-helper`)
- [x] **Long-running mission mode** — steps with `wait:<event>`, checkpoints, resume via events

---

<div align="center">

Built from scratch as a portfolio demonstration of config-driven multi-agent systems · [MIT License](LICENSE)

</div>
