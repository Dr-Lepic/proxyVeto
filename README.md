# proxyVeto

MCP (Model Context Protocol) proxy with JEV-powered gatekeeper for tool call safety evaluation.

## Overview

proxyVeto sits between an MCP client (Claude, Cursor, custom agents) and downstream MCP tool servers. It intercepts `tools/call` requests, evaluates them via JEV (via OpenCode Zen free API) for safety/intent, and either allows, blocks, or escalates to human-in-the-loop.

## Features

- **MCP Proxy**: Transparent stdio/SSE proxy for MCP protocol
- **JEV Evaluation**: Structured safety assessment via OpenCode Zen JEV API
- **Policy Engine**: Configurable ALLOW/BLOCK/ESCALATE decisions
- **Human-in-the-Loop**: Terminal prompt for escalation cases
- **Observability**: Structured JSON logging

## Quickstart

```bash
# Install
uv sync

# Copy example config
cp config.yaml.example config.yaml
# Edit config.yaml with your settings

# Run proxy
uv run proxyveto run --config config.yaml
```

## Configuration

See `config.yaml.example` for all options.

## Architecture

```
[MCP Client] ──► [proxyVeto] ──► [Downstream MCP Servers]
                  │
                  ▼
            [JEV Gatekeeper]
            - is_irreversible
            - blast_radius (1-5)
            - policy_compliance
```

## License

MIT