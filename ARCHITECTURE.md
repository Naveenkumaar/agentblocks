# Architecture

This document explains **how agentblocks is designed and why**. It is written to
match the code exactly — every stage, block, and rule named here maps to a file
you can open. If you change the code, change this doc in the same commit.

- [The core idea](#the-core-idea)
- [Two planes](#two-planes)
- [The block model](#the-block-model)
- [The turn pipeline](#the-turn-pipeline)
- [The connector is the trust boundary](#the-connector-is-the-trust-boundary)
- [The eval gate](#the-eval-gate)
- [Design decisions](#design-decisions)
- [Extending it](#extending-it)

---

## The core idea

**An agent is data, not code.** One generic engine interprets a versioned JSON
document (an [`AgentDefinition`](app/engine/definition.py)) made of *blocks*. You
add a capability by adding a block to the definition — never by writing
agent-specific Python. Because nothing about a specific agent lives in code, the
same engine, guardrails, and eval harness apply to every agent uniformly.

---

## Two planes

The system is split into a **control plane** (authoring/governing agents) and a
**runtime plane** (executing turns). They meet at the shared
[`Registry`](app/engine/registry.py).

```
        CONTROL PLANE                              RUNTIME PLANE
  POST /agents/versions        ┌───────────┐   POST /v1/agents/{name}/turns
  POST /agents/{name}/activate │ Registry  │        │
        │                      │ (versions │        ▼
        ▼                      │  + active)│   ┌──────────┐
   add immutable version       └─────┬─────┘   │  Engine  │  one generic
   activate ── eval gate ────────────┘         │ run_turn │  turn pipeline
   (a version can't go live                     └──────────┘
    until its evals pass)
```

Both planes are served by [`app/main.py`](app/main.py) (FastAPI). The control
plane never executes a turn; the runtime plane never mutates a definition.

---

## The block model

Defined in [`app/engine/definition.py`](app/engine/definition.py). An
`AgentDefinition` is versioned and composed of:

| Block | Type | Responsibility |
|-------|------|----------------|
| `topics` | `Topic[]` | chat/mission surfaces, each with a system prompt + allowed skills |
| `skills` | `Skill[]` | `hydrator` (read-only, safe) or `effector` (acts, carries a `risk_tier`) |
| `connectors` | `Connector[]` | typed boundaries to the world: `http` · `mcp` · `sql` · `static` · `weather` |
| `guardrails` | `Guardrail` | PII tokenize/restore, injection defense, per-audience reveal |
| `knowledge` | `str[]` | document ids for RAG retrieval |
| `governance` | `Governance` | kill switch · session quota · `data_scope` |

A `topic` references `skills` by name; a `skill` references a `connector` by
name. The engine resolves these at runtime — the definition is a graph of names,
not hard-wired objects.

---

## The turn pipeline

One method — [`Engine.run_turn`](app/engine/runtime.py) — runs **every** agent
through the same eight stages. Each stage appends to a `trace`, so a turn is
fully explainable end to end.

```
 message
    │
    ▼
 ┌─────────────┐   the eight stages, in order (app/engine/runtime.py)
 │ 1 ingress   │  record the incoming message
 │ 2 govern    │  kill switch + session quota  (app/governance/checks.py)
 │ 3 guardrails-in │ block injection, tokenize PII  (app/guardrails/)
 │ 4 route     │  pick the topic
 │ 5 assemble  │  memory + knowledge(RAG) + run hydrator skills → context
 │ 6 reason-act│  call the model  (app/engine/model_gateway.py)
 │ 7 guardrails-out │ re-mask per audience (restore PII only if allowed)
 │ 8 egress    │  persist to memory, return reply + trace
 └─────────────┘
    │
    ▼
 reply + trace
```

Stage 5 is where tools run: for each `hydrator` skill on the topic, the engine
builds its connector and calls `invoke(...)`, folding the result into the model
context. Stage 3 blocks and stage 2 refusals short-circuit the pipeline and
still return a coherent reply — a turn never crashes.

---

## The connector is the trust boundary

Enforcement lives **below the model, not in the prompt**. The base
[`Connector.invoke`](app/connectors/base.py) merges the caller's resolved
`scope` into every outbound parameter map *after* the agent's own params, so an
injected "act as another tenant" cannot widen its own access:

```python
scoped = dict(params)
if scope:
    scoped.update(scope)   # scope is injected last — params cannot override it
```

`invoke` also wraps `_call` in try/except and returns `ok=False` on failure, so
a flaky external service degrades gracefully instead of crashing a turn. The
[`weather`](app/connectors/weather_connector.py) connector (live Open-Meteo, no
API key) is the worked example: real network I/O, but a turn still completes if
the network is down.

---

## The eval gate

Versions are **immutable** once created. A version cannot be *activated* (made
live) until it passes its evals —
[`Registry.activate`](app/engine/registry.py) calls the gate and refuses on
failure:

```python
result = gate(definition)          # runs evals/golden.yaml + evals/adversarial.yaml
if not result["passed"]:
    raise PermissionError(...)     # the version stays inactive
```

`golden.yaml` = requests that must be answered; `adversarial.yaml` =
injection/scope-escape attempts that must be refused. This is the one control
that ties correctness to the release step, and it runs in CI
(`python evals/run_eval.py`).

---

## Design decisions

The choices that shape everything above, and the reasoning behind each:

1. **Agents are configuration, not code.** The moment agent behaviour lives in
   Python, a second agent means copy-pasting a pipeline. Making an agent a
   versioned document keeps *one* engine, *one* guardrail path, and *one* eval
   harness for all agents — and lets a non-engineer change behaviour safely.

2. **The connector, not the prompt, is the boundary.** Prompt instructions can
   be talked around; a scope merged into the outbound call below the model
   cannot. Putting enforcement in `invoke` means every tool call is governed the
   same way, regardless of what the model was convinced to do.

3. **Activation is eval-gated and versions are immutable.** Correctness should
   be a property of *release*, not a hope. A version that fails its adversarial
   suite simply cannot go live, and an activated version can never change under
   you.

4. **Every stage is traced.** Explainability isn't a feature bolted on later —
   the pipeline emits a per-stage trace by construction, so any answer can be
   reconstructed from `ingress` to `egress`.

5. **Offline by default, real when you opt in.** The model backend defaults to a
   deterministic stub and the connectors degrade gracefully, so the whole system
   runs with no keys and no network — then you opt into a real model (Ollama) or
   a real tool (Open-Meteo) without touching the engine.

---

## Extending it

- **Add a tool** → write a `Connector` subclass, register its `kind` in
  [`app/connectors/__init__.py`](app/connectors/__init__.py), and reference it
  from an agent's `connectors` block. (The `weather` connector is the template.)
- **Add a capability to an agent** → edit its JSON in
  [`agents/`](agents/) and add an eval case — no engine change.
- **Swap the model** → set `MODEL_BACKEND=ollama`
  ([`app/engine/model_gateway.py`](app/engine/model_gateway.py)); the pipeline is
  unchanged.
- **Add a guardrail** → extend [`app/guardrails/`](app/guardrails/); it runs at
  stages 3 and 7 for every agent automatically.
