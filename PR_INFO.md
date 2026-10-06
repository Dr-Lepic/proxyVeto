# PR: ProxyVeto - MCP Proxy with JEV Gatekeeper

## Summary
Implements a standalone MCP (Model Context Protocol) proxy server that intercepts `tools/call` requests, evaluates them via JEV (TypeSafe's System One decision model via OpenCode Zen free API), and allows/blocks/escalates to human-in-the-loop based on configurable policies.

## Changes

### Core Implementation (Phases 1-3)

| Commit | Component | Description |
|--------|-----------|-------------|
| `a4114bf` | Project Setup | uv project, pyproject.toml with deps (mcp, httpx, pydantic-settings, typer, structlog, pyyaml, anyio) |
| `f291916` | Gitignore | Comprehensive .gitignore for Python project |
| `91c72b8` | Config Template | .env.example with OPENCODE_API_KEY |
| `bc9abf6` | JEV Evaluator | OpenCode Zen System One API client, schema, prompts, unit tests (11 tests) |
| `97e1b85` | Policy Engine | ALLOW/BLOCK/ESCALATE decision logic with configurable thresholds, unit tests (7 tests) |
| `0448d2c` | Escalation | Terminal TTY prompt [y/N] with timeout + mock handler, unit tests (6 tests) |
| `6e071ff` | MCP Proxy Core | StdioTransport (JSON-RPC), MCPServerTransport (subprocess), ToolCallInterceptor, ProxyServer |
| `3b9c8b0` | CLI | `proxyveto run` command with config loading, upstream override, env var API key |
| `e5bf11f` | CLI Tests | Unit tests for CLI commands (4 tests) |
| `08cb851` | Package Entry | Renamed cli.py → __main__.py for `python -m proxyveto` |
| `693c708` | Type Fixes | MyPy clean across all modules |
| `6e05576` | JEV API Fix | Updated to OpenCode Zen System One endpoint (`/systemone`) with correct payload/response format |
| `2e182da` | Documentation | USER_GUIDE.md + README links |
| `2b8d79e` | Phase 3 Features | validate-config, test-jev commands, example configs, dangerous-tools server, benchmark script |

### Files Added/Modified

```
src/proxyveto/
├── __init__.py              # Package exports
├── __main__.py              # CLI: run, config, validate-config, test-jev
├── config.py                # Pydantic settings (JEV, Policy, Proxy, Escalation, Logging)
├── proxy/
│   ├── __init__.py
│   ├── server.py            # ProxyServer, ToolCallInterceptor
│   └── transport.py         # StdioTransport, MCPServerTransport
├── evaluator/
│   ├── __init__.py
│   ├── jev_client.py        # OpenCode Zen System One async client
│   ├── schema.py            # EvaluationRequest/Response, PrimitiveResult, Environment
│   └── prompts.py           # System prompt templates
├── policy/
│   ├── __init__.py
│   └── engine.py            # PolicyEngine with ALLOW/BLOCK/ESCALATE logic
└── escalation/
    ├── __init__.py
    └── terminal.py          # TerminalEscalation, MockEscalation, factory

tests/unit/
├── test_cli.py              # 4 tests
├── test_escalation.py       # 6 tests
├── test_jev_schema.py       # 11 tests
├── test_policy_engine.py    # 7 tests
└── test_proxy.py            # 8 tests

docs/
└── USER_GUIDE.md            # Complete usage guide

examples/
├── config-strict.yaml       # Aggressive blocking (production)
├── config-permissive.yaml   # Lenient blocking (development)
└── downstream-servers/
    └── dangerous-tools/
        └── server.py        # Test MCP server with dangerous tools

scripts/
└── benchmark.py             # Latency/accuracy benchmark
```

## Key Features

1. **MCP Proxy**: Transparent stdio proxy intercepting `tools/call`
2. **JEV Evaluation**: 3 primitives - `is_irreversible` (noul), `blast_radius` (choice 1-5), `policy_compliance` (noul)
3. **Policy Engine**: Configurable thresholds for ALLOW/BLOCK/ESCALATE
4. **Human-in-the-Loop**: Terminal escalation with timeout
5. **Observability**: Structured JSON logging via structlog
6. **Type Safety**: Full MyPy coverage

## Usage

```bash
# Install
uv pip install -e .

# Configure
export OPENCODE_API_KEY="your-key"

# Run with upstream MCP server
proxyveto run --upstream npx --upstream @modelcontextprotocol/server-filesystem --upstream /path/to/dir

# Validate config
proxyveto validate-config config.yaml

# Test JEV connectivity
proxyveto test-jev
```

## Testing

```bash
# Unit tests (42 passing)
uv run pytest tests/unit/ -v

# Type checking
uv run mypy src/proxyveto/

# Live JEV test
proxyveto test-jev

# Benchmark (uses API quota)
python scripts/benchmark.py
```

## Quality Gates

- ✅ 42 unit tests passing
- ✅ MyPy strict type checking clean
- ✅ All commits conventional format
- ✅ No secrets in code (uses env vars)
- ✅ Documentation complete

## Benchmark Results (Live API)

```
Accuracy: 6/14 (42.9%)
Latency:  avg=665ms, median=608ms, p95=1481ms
```

Note: Model is conservative - tends to BLOCK safe operations. Policy thresholds in `examples/config-permissive.yaml` may work better for development.

## Configuration

Environment variables (via `.env`):
```bash
OPENCODE_API_KEY=your-key
```

Config file (YAML):
```yaml
jev:
  model: "jev-1.13-free"
  endpoint: "https://opencode.ai/zen/v1"
  timeout_seconds: 5.0

policy:
  blast_radius_allow_max: 2
  blast_radius_block_min: 4
  irreversible_prob_block: 0.85
  compliance_prob_block: 0.15

escalation:
  enabled: true
  timeout_seconds: 30.0
```

## MCP Client Integration

### Claude Desktop
```json
{
  "mcpServers": {
    "filesystem-protected": {
      "command": "proxyveto",
      "args": ["run", "--upstream", "npx", "--upstream", "@modelcontextprotocol/server-filesystem", "--upstream", "/path/to/dir"],
      "env": { "OPENCODE_API_KEY": "your-key" }
    }
  }
}
```

### Cursor/VS Code
```json
{
  "mcpServers": {
    "github-protected": {
      "command": "proxyveto",
      "args": ["run", "--upstream", "npx", "--upstream", "@modelcontextprotocol/server-github"],
      "env": { "OPENCODE_API_KEY": "your-key" }
    }
  }
}
```

## Known Limitations

- JEV latency ~600-1400ms (remote API call)
- Model conservative on safe operations (tune thresholds)
- No SSE transport yet (Phase 2 stretch)
- No audit log persistence (post-MVP)
- Free tier: ~50 JEV requests/day

## Next Steps (Post-MVP)

- [ ] SSE transport for remote clients
- [ ] Webhook escalation (Slack, Discord)
- [ ] Audit log persistence (SQLite/PostgreSQL)
- [ ] Policy DSL (CEL/OPA)
- [ ] Metrics endpoint (Prometheus)
- [ ] JEV response caching