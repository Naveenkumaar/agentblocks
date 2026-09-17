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
- [Code-level flow](#code-level-flow)
- [Problems faced & how I fixed them](#problems-faced--how-i-fixed-them)
- [What this is capable of](#what-this-is-capable-of)
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
 │ 6b effect   │  run effector skills; a high-risk one suspends for approval
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

## Code-level flow

Follow one `POST /v1/agents/{name}/turns` request through the code, function by
function. Every step names the file so you can open it and read along.

```
app/main.py : run_turn()                      ← HTTP entry
  │  registry.get(name)                        app/engine/registry.py
  │      → returns the active AgentDefinition   app/engine/definition.py
  ▼
app/engine/runtime.py : Engine.run_turn(agent, message, ...)
  │
  ├─ 1 ingress   step("ingress", ...)          → append to trace
  │
  ├─ 2 govern    enforce(agent.governance, memory.turn_count(session))
  │              app/governance/checks.py       → raises GovernanceError → early return
  │
  ├─ 3 guardrails-in
  │      detect_injection(message)             app/guardrails/injection.py
  │          → (True, signal) ⇒ block + return
  │      redact_pii(message)                    app/guardrails/redact.py
  │          → (safe_message, vault)            vault = {token: original}
  │
  ├─ 4 route     agent.topic(topic_name)       app/engine/definition.py
  │          → the Topic (system_prompt + allowed skill names)
  │
  ├─ 5 assemble  self._run_hydrators(agent, topic, safe_message, scope, step)
  │      └─ for each hydrator skill on the topic:
  │             spec = agent.connector(skill.connector)      definition.py
  │             connector = build_connector(spec)            app/connectors/__init__.py
  │             res = connector.invoke({"query": ...}, scope)  ← THE TRUST BOUNDARY
  │                   app/connectors/base.py : Connector.invoke()
  │                     scoped = {**params, **scope}   # scope injected LAST
  │                     try: return _call(scoped)       # subclass does real I/O
  │                     except: return ok=False         # never crashes the turn
  │      context = history + knowledge(RAG) + tool results
  │
  ├─ 6 reason-act  self.model.generate(system_prompt, safe_message, context)
  │                app/engine/model_gateway.py  (StubModel offline | OllamaModel real)
  │
  ├─ 7 guardrails-out
  │      if vault and audience allowed: restore(reply, vault)   redact.py
  │          → detokenize PII only for an authorized audience
  │
  └─ 8 egress    memory.append(session, ...)   app/memory/store.py
                 return TurnResult(reply, blocked, reason, trace)
```

And the **activation path** (control plane), which is separate:

```
app/main.py : activate(name, version)
  → registry.activate(name, version, gate)      app/engine/registry.py
       result = gate(definition)                 evals/run_eval.py : evaluate()
           runs golden.yaml + adversarial.yaml through Engine.run_turn
       if not result["passed"]: raise PermissionError   ← version stays inactive
       else: self._active[name] = version
```

The two paths never touch each other's state: `run_turn` only reads a definition,
`activate` only writes the active-version pointer after the gate passes.

---

## Problems faced & how I fixed them

The decisions above came from concrete problems. This is the record of them —
the "why it looks like this."

| Problem | Symptom | Fix (in the code) |
|--------|---------|-------------------|
| **Prompt injection reaching tools** | A crafted message ("act as another tenant") could make the model call a connector outside its scope. | Enforcement moved *below the model*: `Connector.invoke` merges the caller's `scope` **last** (`{**params, **scope}`), so params can't override it — the prompt can't widen access. Gated by the adversarial eval suite. |
| **A flaky external tool crashed the whole turn** | One failing HTTP call raised and killed the request. | `Connector.invoke` wraps `_call` in try/except and returns `ok=False`; stage 5 still assembles context and the turn completes with a graceful answer. |
| **"Which version is live?" was ambiguous** | Editing an agent silently changed behaviour under running traffic. | Versions are **immutable** once created; going live requires `registry.activate`, and the active pointer only moves after the eval gate passes. |
| **Bad versions could ship** | Nothing tied correctness to release. | `activate()` runs `golden.yaml` (must answer) + `adversarial.yaml` (must refuse) and **refuses activation** below threshold — correctness is a property of release. |
| **Couldn't explain an answer after the fact** | No record of why a reply happened. | Every stage appends to a `trace`; a turn is reconstructable end to end from `ingress` to `egress` (visible in the console). |
| **Needed to demo without keys/network** | Onboarding required an API key just to see it run. | Model + connectors default to offline stubs (`StubModel`, graceful connector failure); real backends (Ollama, Open-Meteo) are opt-in via env var — no engine change. |
| **PII leaking to logs/model** | Raw user data flowed into the model and traces. | `redact_pii` tokenizes on the way in; `restore` detokenizes only for an allowed audience on the way out — the model and traces see tokens. |
| **One identity both requesting and authorising a risky action** | An agent could trigger a high-impact effector with no second check. | Effectors at/above `approval_required_tier` **suspend** and create an approval; `ApprovalStore.decide` enforces `checker != maker` before the action runs. |

---

## What this is capable of

- **Define an agent as data** — ship a new agent by writing a JSON definition and an eval case; zero engine code.
- **Multi-tool turns** — a topic's hydrator skills call any mix of `http` / `mcp` / `static` / `weather` connectors, each governed by the same scope boundary.
- **Live external tools** — the `weather` connector calls Open-Meteo (real geocoding + forecast, no API key) as a worked example.
- **Grounded, guarded responses** — RAG context + PII tokenization + prompt-injection refusal on every turn.
- **Release safety** — immutable versions, eval-gated activation, kill switch, and per-session quotas.
- **Maker-checker on risky actions** — an `effector` skill at/above the agent's `approval_required_tier` doesn't execute; it suspends the turn and records a pending approval that a *different* person must approve (`checker != maker`) before it runs (`app/governance/approvals.py`, `POST /approvals/{id}/decide`).
- **Full explainability + timing** — a per-stage trace for every turn, each stage stamped with its latency (`ms`) and a running total, surfaced in a self-contained operator console (Configure / Simulate / Chat).
- **Streaming turns** — `run_turn_stream` yields `{token}` events during reason-act then a final `{done}` (full reply + trace); exposed at `POST /v1/agents/{name}/turns/stream` as SSE and rendered live in the console.
- **Runs anywhere** — offline by default (no keys, no network); opt into a local model and live tools without touching the pipeline.

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
