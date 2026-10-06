# proxyVeto — MCP Proxy with JEV Gatekeeper

## Project Overview

**proxyVeto** is a standalone MCP (Model Context Protocol) proxy server that sits between an MCP client (Claude, Cursor, custom agent) and downstream MCP tool servers. It intercepts `tools/call` requests, evaluates them via **JEV** (via OpenCode Zen free API) for safety/intent, and either allows, blocks, or escalates to human-in-the-loop (terminal prompt).

---

## Architecture

```
┌─────────────────┐     stdio/SSE      ┌──────────────────┐     stdio/SSE      ┌────────────────────┐
│  MCP Client     │◄──────────────────►│   proxyVeto      │◄──────────────────►│  Downstream MCP    │
│  (Claude,       │   JSON-RPC 2.0     │   (Gatekeeper)   │   JSON-RPC 2.0     │  Tool Servers      │
│   Cursor,       │                    │                  │                    │  (terminal, GitHub,│
│   custom)       │                    │  ┌────────────┐  │                    │   SQL, etc.)       │
└─────────────────┘                    │  │ JEV Client │  │                    └────────────────────┘
                                       │  │ (OpenCode  │  │
                                       │  │  Zen)      │  │
                                       │  └────────────┘  │
                                       │  ┌────────────┐  │
                                       │  │ Policy     │  │
                                       │  │ Engine     │  │
                                       │  └────────────┘  │
                                       └──────────────────┘
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **MCP Proxy Core** | Bidirectional JSON-RPC 2.0 proxy over stdio (MVP) / SSE (v2). Forwards `initialize`, `tools/list`, `resources/*` transparently. Intercepts `tools/call`. |
| **JEV Evaluator** | Calls JEV via OpenCode Zen API with structured payload: `tool_name`, `arguments`, `declared_intent`, `environment`. Parses `is_irreversible` (bool prob), `blast_radius` (1-5 score), `policy_compliance` (bool prob). |
| **Policy Engine** | Maps JEV outputs → `ALLOW` / `BLOCK` / `ESCALATE` using configurable thresholds. |
| **Escalation Handler** | Terminal stdin `[y/N]` prompt for `ESCALATE`. Returns approval/denial to proxy. |
| **Config System** | YAML config for thresholds, JEV endpoint, policy presets, logging. |

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Language** | Python 3.11+ | Aligns with JEV eval scripts, agent ecosystems, async stdlib |
| **Async Runtime** | `asyncio` + `anyio` | Native async, works with stdio/SSE |
| **MCP Protocol** | `mcp` Python SDK (official) | Spec-compliant, handles JSON-RPC framing |
| **HTTP Client** | `httpx` | Async, supports OpenCode Zen API |
| **Config** | `pydantic-settings` + YAML | Type-safe, env var override |
| **CLI** | `typer` | Modern, rich help, subcommands |
| **Logging** | `structlog` | Structured JSON logs for observability |
| **Testing** | `pytest` + `pytest-asyncio` | Standard, async support |
| **Packaging** | `uv` + `pyproject.toml` | Fast, modern, matches user toolchain |

---

## Project Structure

```
proxyVeto/
├── pyproject.toml
├── uv.lock
├── README.md
├── config.yaml.example
├── src/
│   └── proxyveto/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry: `proxyveto run --config config.yaml`
│       ├── config.py            # Pydantic settings model
│       ├── proxy/
│       │   ├── __init__.py
│       │   ├── server.py        # MCP proxy server (stdio/SSE)
│       │   ├── transport.py     # stdio + SSE transport adapters
│       │   └── interceptor.py   # tools/call interception logic
│       ├── evaluator/
│       │   ├── __init__.py
│       │   ├── jev_client.py    # OpenCode Zen JEV API client
│       │   ├── schema.py        # Evaluation request/response models
│       │   └── prompts.py       # System prompt templates
│       ├── policy/
│       │   ├── __init__.py
│       │   ├── engine.py        # Decision mapping (ALLOW/BLOCK/ESCALATE)
│       │   └── models.py        # Policy config, thresholds
│       ├── escalation/
│       │   ├── __init__.py
│       │   └── terminal.py      # stdin [y/N] prompt handler
│       └── utils/
│           ├── __init__.py
│           └── logging.py       # structlog setup
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_policy_engine.py
│   │   ├── test_jev_schema.py
│   │   └── test_config.py
│   └── integration/
│       ├── test_proxy_stdio.py
│       └── test_jev_integration.py
├── scripts/
│   ├── dev-run.sh               # Quick dev run with example config
│   └── benchmark.py             # Latency/accuracy benchmark vs LLM guard
└── examples/
    ├── config-strict.yaml
    ├── config-permissive.yaml
    └── downstream-servers/      # Example MCP servers for testing
        └── dangerous-tools/     # Server with rm, sql, etc.
```

---

## Detailed Implementation Plan

### Phase 1: Foundation (Week 1)

#### 1.1 Project Setup
- [ ] Initialize `uv` project: `uv init proxyVeto`
- [ ] Add dependencies to `pyproject.toml`: `mcp`, `httpx`, `pydantic-settings`, `typer`, `structlog`, `pyyaml`, `anyio`
- [ ] Configure `ruff` + `mypy` for linting/type-checking
- [ ] Set up `pre-commit` hooks

#### 1.2 Configuration System
- [ ] Define `Config` model in `config.py`:
  - `jev`: endpoint, model, timeout, api_key (from env)
  - `policy`: `blast_radius_allow_max`, `irreversible_prob_block`, `compliance_prob_block`
  - `proxy`: transport (`stdio`/`sse`), host, port, upstream_servers (list of command/args)
  - `escalation`: enabled, timeout_seconds
  - `logging`: level, format
- [ ] Create `config.yaml.example` with documented defaults

#### 1.3 JEV Evaluator Client
- [ ] Implement `JEVClient` in `evaluator/jev_client.py`:
  - Async HTTP client to OpenCode Zen endpoint
  - Request schema: `tool_name`, `arguments`, `declared_intent`, `environment`
  - Response schema: `is_irreversible` (prob), `blast_radius` (1-5), `policy_compliance` (prob)
  - Retry logic (exponential backoff, max 3)
  - Timeout handling (configurable, default 5s)
- [ ] Define Pydantic models in `evaluator/schema.py`
- [ ] Create system prompt templates in `evaluator/prompts.py` (few-shot examples)

#### 1.4 Policy Engine
- [ ] Implement `PolicyEngine` in `policy/engine.py`:
  - Input: JEV evaluation result
  - Logic:
    ```
    if blast_radius <= allow_max AND irreversible_prob < block_thresh AND compliance_prob > comply_thresh:
        return ALLOW
    elif blast_radius >= 4 OR irreversible_prob > 0.85 OR compliance_prob < 0.15:
        return BLOCK
    else:
        return ESCALATE
    ```
  - Configurable thresholds via `PolicyConfig`
- [ ] Unit tests for all decision boundaries

### Phase 2: MCP Proxy Core (Week 2)

#### 2.1 Transport Layer
- [ ] Implement `StdioTransport` in `proxy/transport.py`:
  - Read JSON-RPC frames from stdin (newline-delimited)
  - Write responses to stdout
  - Handle `Content-Length` headers if present
- [ ] Implement `SSETransport` (stretch, for v2)

#### 2.2 Proxy Server
- [ ] Implement `ProxyServer` in `proxy/server.py`:
  - Maintain upstream MCP server connections (subprocesses via stdio)
  - Forward `initialize`, `tools/list`, `resources/*`, `prompts/*` transparently
  - Intercept `tools/call` → evaluate → decide → forward or respond with error
  - Request/response correlation (JSON-RPC `id` mapping)
  - Graceful shutdown (terminate upstreams on exit)

#### 2.3 Interception Logic
- [ ] Implement `ToolCallInterceptor` in `proxy/interceptor.py`:
  - Extract `tool_name`, `arguments` from `tools/call` params
  - Build `declared_intent` from recent conversation context (last user message + agent reasoning if available)
  - Call `JEVClient.evaluate()`
  - Call `PolicyEngine.decide()`
  - On `ALLOW`: forward to upstream
  - On `BLOCK`: return JSON-RPC error with reason
  - On `ESCALATE`: call escalation handler, then allow/block based on human response

#### 2.4 Terminal Escalation
- [ ] Implement `TerminalEscalation` in `escalation/terminal.py`:
  - Print tool call details (name, args, JEV scores)
  - Blocking `input("[y/N] ")`
  - Return `True`/`False`
  - Respect configurable timeout (default 30s → auto-block)

### Phase 3: Integration & Polish (Week 3)

#### 3.1 CLI & Packaging
- [ ] Implement `proxyveto run` command in `__main__.py`:
  - Load config from file + env overrides
  - Start proxy server
  - Handle signals (SIGTERM, SIGINT)
- [ ] Add `proxyveto validate-config` command
- [ ] Add `proxyveto test-jev` command (sanity check JEV connectivity)

#### 3.2 Example Configs & Downstream Servers
- [ ] Create `examples/config-strict.yaml` (low thresholds, aggressive blocking)
- [ ] Create `examples/config-permissive.yaml` (high thresholds, mostly allow)
- [ ] Set up example dangerous-tools MCP server (shell, file write, SQL)

#### 3.3 Benchmarking Script
- [ ] Implement `scripts/benchmark.py`:
  - Synthetic test set: 50 risky / 50 benign tool calls
  - Measure latency (target: <100ms p99)
  - Compare accuracy vs LLM prompt-guard baseline
  - Output markdown report

#### 3.4 Documentation
- [ ] Write `README.md`: install, quickstart, config reference, architecture
- [ ] Add usage examples for Claude Desktop, Cursor, custom agents

---

## Configuration Schema (config.yaml)

```yaml
jev:
  endpoint: "https://api.opencode.ai/v1/decisions"  # OpenCode Zen endpoint
  model: "jev"
  timeout_seconds: 5
  # api_key from OPENCODE_API_KEY env var

policy:
  blast_radius_allow_max: 2      # 1-5, allow if <= this
  irreversible_prob_block: 0.85  # block if irreversible prob > this
  compliance_prob_block: 0.15    # block if compliance prob < this

proxy:
  transport: "stdio"             # "stdio" | "sse"
  host: "127.0.0.1"
  port: 8080
  upstream_servers:
    - name: "terminal"
      command: ["mcp-server-terminal"]
      args: []
    - name: "github"
      command: ["mcp-server-github"]
      args: ["--token", "${GITHUB_TOKEN}"]

escalation:
  enabled: true
  timeout_seconds: 30

logging:
  level: "INFO"
  format: "json"                 # "json" | "console"
```

---

## JEV Evaluation Payload

```json
{
  "tool_name": "execute_shell_command",
  "arguments": {"command": "rm -rf ./tmp"},
  "declared_intent": "User asked me to clean up temporary files in the project directory.",
  "environment": "local_fs"
}
```

**JEV Response (expected):**
```json
{
  "is_irreversible": {"probability": 0.95, "label": true},
  "blast_radius": {"score": 4, "label": "high"},
  "policy_compliance": {"probability": 0.10, "label": false}
}
```

---

## Decision Policy Mapping (Configurable)

| Condition | Action |
|-----------|--------|
| `blast_radius <= allow_max` AND `irreversible_prob < block_thresh` AND `compliance_prob > comply_thresh` | `ALLOW` |
| `blast_radius >= 4` OR `irreversible_prob > 0.85` OR `compliance_prob < 0.15` | `BLOCK` |
| Otherwise | `ESCALATE` |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| JEV latency >100ms | Async eval, configurable timeout, cache repeated calls |
| OpenCode Zen rate limits | Local fallback stub, request batching, queue |
| False positives (blocking safe calls) | Permissive default config, logging for tuning |
| False negatives (allowing dangerous calls) | Conservative defaults, blast_radius >= 4 always blocks |
| Upstream MCP server crashes | Health checks, auto-restart, circuit breaker |
| JSON-RPC framing errors | Robust parsing, log raw frames on error |

---

## Success Criteria (MVP)

- [ ] `proxyveto run` starts proxy, connects to 1+ upstream MCP servers
- [ ] `tools/call` interception works: safe calls pass, dangerous calls blocked
- [ ] JEV evaluation completes in <100ms p99 (local network to OpenCode Zen)
- [ ] Terminal escalation prompts human, respects decision
- [ ] Configurable thresholds via YAML + env vars
- [ ] Structured JSON logs for all decisions
- [ ] Unit tests >80% coverage on policy/evaluator
- [ ] Integration test with real downstream MCP server

---

## Future Enhancements (Post-MVP)

- SSE transport for remote clients
- Webhook escalation (Slack, Discord, PagerDuty)
- Audit log persistence (SQLite/PostgreSQL)
- Policy DSL (CEL/OPA) for complex rules
- Metrics endpoint (Prometheus)
- Multi-tenant proxy with per-client policies
- JEV response caching for repeated identical calls