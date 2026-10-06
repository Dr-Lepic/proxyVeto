# ProxyVeto User Guide

ProxyVeto is an MCP (Model Context Protocol) proxy server that intercepts tool calls, evaluates them for safety using JEV (TypeSafe's System One decision model via OpenCode Zen), and allows/blocks/escalates based on configurable policies.

## Quick Start

### Installation

```bash
# From source
git clone https://github.com/your-repo/proxyVeto
cd proxyVeto
uv pip install -e .

# Or with pip
pip install -e .
```

### Configuration

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` and add your OpenCode Zen API key:
```bash
OPENCODE_API_KEY=your-api-key-here
```

Get your free API key from [OpenCode Zen](https://opencode.ai/zen).

### Basic Usage

Run the proxy with an upstream MCP server:

```bash
# Filesystem server (read-only by default)
proxyveto run --upstream npx --upstream @modelcontextprotocol/server-filesystem --upstream /path/to/dir

# GitHub server
proxyveto run --upstream npx --upstream @modelcontextprotocol/server-github

# Custom server
proxyveto run --upstream python -m my_mcp_server
```

The proxy starts on stdio and forwards JSON-RPC messages to the upstream server after evaluation.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│ MCP Client  │────▶│  ProxyVeto   │────▶│  JEV Model   │────▶│  Policy     │
│ (Claude,    │     │  (Proxy)     │     │  (OpenCode   │     │  Engine     │
│  Cursor)    │     │              │     │   Zen)       │     │             │
└─────────────┘     └──────┬───────┘     └──────┬───────┘     └──────┬──────┘
                           │                    │                    │
                    ┌──────▼───────┐     ┌──────▼───────┐     ┌──────▼──────┐
                    │ Intercept    │     │ Evaluate     │     │ Decide:     │
                    │ tools/call   │     │ 3 primitives │     │ ALLOW/      │
                    │ messages     │     │              │     │ BLOCK/      │
                    └──────────────┘     └──────────────┘     │ ESCALATE    │
                                                          └──────┬──────┘
                                                                 │
                                                          ┌──────▼──────┐
                                                          │ Escalation  │
                                                          │ Handler     │
                                                          │ (Terminal   │
                                                          │  prompt)    │
                                                          └─────────────┘
```

## JEV Evaluation

Each tool call is evaluated on three primitives:

| Primitive | Type | Description |
|-----------|------|-------------|
| **is_irreversible** | noul (yes/no) | Can this action be undone? |
| **blast_radius** | choice (1-5) | Scope of impact |
| **policy_compliance** | noul (yes/no) | Does it comply with security policy? |

### Blast Radius Scale

| Score | Description | Examples |
|-------|-------------|----------|
| 1 | Read-only local | `read_file`, `list_directory` |
| 2 | Local write | `write_file`, `create_directory` |
| 3 | Network read | HTTP GET, DNS query |
| 4 | Network write | POST, PUT, DELETE, API calls |
| 5 | Destructive/credential exfiltration | `rm -rf`, format disk, send secrets |

## Policy Engine

The policy engine maps JEV scores to decisions:

| Decision | Criteria |
|----------|----------|
| **ALLOW** | `blast_radius ≤ allow_max` AND `irreversible_prob < block_threshold` AND `compliance_prob > block_threshold` |
| **BLOCK** | `blast_radius ≥ block_min` OR `irreversible_prob ≥ block_threshold` OR `compliance_prob ≤ block_threshold` |
| **ESCALATE** | Medium risk - not clearly allow or block |

### Default Thresholds

```yaml
policy:
  blast_radius_allow_max: 2      # Allow up to local write
  blast_radius_block_min: 4      # Block network write and above
  irreversible_prob_block: 0.85  # Block if >85% chance irreversible
  compliance_prob_block: 0.15    # Block if <15% chance compliant
```

## Escalation

When a call is escalated, the proxy prompts for human approval:

```
⚠️  ESCALATION REQUIRED
Tool: execute_shell_command
Arguments: {"command": "rm -rf /tmp/test"}
Intent: Clean up temp files
JEV Assessment:
  - Irreversible: 12% (no)
  - Blast Radius: 3 (network read)
  - Policy Compliance: 45% (no)

Allow this action? [y/N]:
```

- **Timeout**: Default 30 seconds (configurable)
- **Default**: No (safe default)
- **TTY Required**: Falls back to BLOCK if no TTY available

## MCP Client Integration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "filesystem-protected": {
      "command": "proxyveto",
      "args": [
        "run",
        "--upstream", "npx",
        "--upstream", "@modelcontextprotocol/server-filesystem",
        "--upstream", "/Users/you/Documents"
      ],
      "env": {
        "OPENCODE_API_KEY": "your-key"
      }
    }
  }
}
```

### Cursor / VS Code

Add to `.cursor/mcp.json`:

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

### Generic MCP Client

Any MCP client that supports stdio transport can use proxyVeto by setting it as the command with the upstream server as arguments.

## Configuration File

Generate a config template:

```bash
proxyveto config -o config.yaml
```

Full config options:

```yaml
# config.yaml
jev:
  endpoint: "https://opencode.ai/zen/v1"
  model: "jev-1.13-free"
  timeout_seconds: 5.0
  max_retries: 2
  api_key: "${OPENCODE_API_KEY}"

policy:
  blast_radius_allow_max: 2
  blast_radius_block_min: 4
  irreversible_prob_block: 0.85
  compliance_prob_block: 0.15

proxy:
  upstream_command: []  # Overridden by CLI --upstream

escalation:
  enabled: true
  timeout_seconds: 30.0
  default_allow: false

logging:
  level: "INFO"
  format: "json"
```

Use with:
```bash
proxyveto run --config config.yaml --upstream npx --upstream @modelcontextprotocol/server-filesystem --upstream /path/to/dir
```

## CLI Reference

```
proxyveto [OPTIONS] COMMAND [ARGS]...

Commands:
  run    Run the MCP proxy server
  config Generate a configuration file template

Run Options:
  --config FILE              Path to config.yaml
  --upstream COMMAND [ARGS]  Upstream MCP server command (repeatable)
  --jev-api-key KEY          JEV API key (overrides env/config)
  --no-escalation            Disable human-in-the-loop escalation
  --escalation-timeout SEC   Escalation prompt timeout (default: 30)
  --log-level LEVEL          Log level: DEBUG/INFO/WARNING/ERROR
  --help                     Show help
```

## Using as a Library

```python
from proxyveto import JEVClient, EvaluationRequest, Environment
from proxyveto.config import JEVConfig

config = JEVConfig()  # Loads from .env
client = JEVClient(config)

async with client:
    request = EvaluationRequest(
        tool_name="execute_shell_command",
        arguments={"command": "ls -la"},
        declared_intent="List files",
        environment=Environment.LOCAL_FS
    )
    context = await client.evaluate_with_retry(request)
    
    # Access structured results
    print(f"Irreversible: {context.response.is_irreversible.probability:.0%}")
    print(f"Blast Radius: {context.response.blast_radius.score}/5")
    print(f"Compliance: {context.response.policy_compliance.probability:.0%}")
```

## Troubleshooting

### "JEV request failed: Expecting value"
- Check your `OPENCODE_API_KEY` is valid
- Verify internet connectivity to `opencode.ai`
- Check API quota (free tier: ~50 requests/day)

### "Escalation timeout"
- Increase timeout: `--escalation-timeout 60`
- Or disable: `--no-escalation` (will BLOCK instead)

### Upstream server not starting
- Verify the command works standalone: `npx @modelcontextprotocol/server-filesystem /path`
- Check server logs in proxy output

### MCP client can't connect
- Ensure proxyveto is in PATH (or use full path)
- Check Claude Desktop logs: `~/Library/Logs/Claude/`

## Security Considerations

- **API keys**: Never commit `.env` - use `.env.example` template
- **Free tier limits**: ~50 JEV requests/day on OpenCode Zen free tier
- **Fail-open**: JEV errors default to ESCALATE (human decides)
- **No persistence**: Proxy doesn't store tool calls or decisions
- **Audit trail**: Structured JSON logs for review

## Advanced

### Custom Policy

```python
from proxyveto.policy import PolicyEngine, PolicyConfig

config = PolicyConfig(
    blast_radius_allow_max=1,  # Read-only only
    blast_radius_block_min=3,  # Block network read+
    irreversible_prob_block=0.5,
    compliance_prob_block=0.5
)
engine = PolicyEngine(config)
decision = engine.decide(evaluation_response)
```

### Custom Escalation Handler

```python
from proxyveto.escalation import EscalationHandler, EscalationContext, EscalationDecision

class SlackEscalation(EscalationHandler):
    async def escalate(self, context: EscalationContext) -> EscalationDecision:
        # Send to Slack, wait for reaction/button click
        # Return EscalationDecision(action="ALLOW" or "BLOCK", reason="...")
        pass

# Use in proxy
from proxyveto.proxy import ProxyServer, ToolCallInterceptor

interceptor = ToolCallInterceptor(
    jev_client=client,
    policy_engine=engine,
    escalation_handler=SlackEscalation()
)
```

## Links

- [OpenCode Zen](https://opencode.ai/zen) - Free JEV API access
- [MCP Specification](https://modelcontextprotocol.io/)
- [JEV Documentation](https://docs.typesafe.ai/)
- [Project Plan](docs/PROJECT_PLAN.md)