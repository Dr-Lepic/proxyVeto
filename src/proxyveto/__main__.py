from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.console import Console

from proxyveto.config import Config, load_config
from proxyveto.proxy.server import ProxyServer

app = typer.Typer(
    name="proxyveto",
    help="ProxyVeto - MCP proxy server with JEV-based tool call interception",
    add_completion=False,
)

console = Console()


@app.command()
def run(
    config_path: Annotated[str | None, typer.Option("--config", "-c", help="Path to config YAML file")] = None,
    upstream_command: Annotated[list[str] | None, typer.Option("--upstream", "-u", help="Upstream MCP server command (e.g., 'mcp-server-sqlite')")] = None,
    jev_api_key: Annotated[str | None, typer.Option("--jev-api-key", envvar="OPENCODE_API_KEY", help="OpenCode Zen JEV API key")] = None,
    escalation_enabled: Annotated[bool, typer.Option("--escalation/--no-escalation", help="Enable human-in-the-loop escalation")] = True,
    escalation_timeout: Annotated[float, typer.Option("--escalation-timeout", help="Escalation timeout in seconds")] = 30.0,
    log_level: Annotated[str, typer.Option("--log-level", help="Log level (DEBUG, INFO, WARNING, ERROR)")] = "INFO",
) -> None:
    """Run the ProxyVeto MCP proxy server."""
    try:
        # Load configuration
        if config_path:
            config = load_config(config_path)
        else:
            # Build config from CLI args and environment
            config = build_config_from_cli(
                upstream_command=upstream_command,
                jev_api_key=jev_api_key,
                escalation_enabled=escalation_enabled,
                escalation_timeout=escalation_timeout,
                log_level=log_level,
            )

        # Validate config
        if not config.proxy.upstream_servers:
            console.print("[red]Error: No upstream servers configured. Use --upstream or config file.[/red]")
            sys.exit(1)

        if not config.jev.api_key:
            console.print("[red]Error: JEV API key required. Set OPENCODE_API_KEY env var or use --jev-api-key.[/red]")
            sys.exit(1)

        # Run server
        console.print(f"[green]Starting ProxyVeto on {len(config.proxy.upstream_servers)} upstream server(s)...[/green]")
        for upstream in config.proxy.upstream_servers:
            console.print(f"  - {upstream.name}: {' '.join(upstream.command)}")

        server = ProxyServer(config)
        import asyncio
        asyncio.run(server.start())

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def build_config_from_cli(
    upstream_command: list[str] | None,
    jev_api_key: str | None,
    escalation_enabled: bool,
    escalation_timeout: float,
    log_level: str,
) -> Config:
    """Build config from CLI arguments."""
    from proxyveto.config import (
        JEVConfig,
        PolicyConfig,
        EscalationConfig,
        ProxyConfig,
        UpstreamServerConfig,
    )

    # Build upstream servers
    upstream_servers = []
    if upstream_command:
        upstream_servers.append(
            UpstreamServerConfig(
                name="upstream-1",
                command=upstream_command,
            )
        )

    return Config(
        jev=JEVConfig(api_key=jev_api_key),
        policy=PolicyConfig(),
        escalation=EscalationConfig(
            enabled=escalation_enabled,
            timeout_seconds=escalation_timeout,
        ),
        proxy=ProxyConfig(upstream_servers=upstream_servers),
    )


@app.command()
def config(
    output: Annotated[str | None, typer.Option("--output", "-o", help="Output config file path")] = None,
) -> None:
    """Generate example configuration file."""
    example_config = """# ProxyVeto Configuration
# Save as config.yaml and use with: proxyveto run --config config.yaml

jev:
  api_key: "${OPENCODE_API_KEY}"  # Or set OPENCODE_API_KEY environment variable
  model: "jev"
  base_url: "https://api.opencode.ai/v1"
  timeout_seconds: 5.0
  max_retries: 2

policy:
  blast_radius_allow_max: 2
  irreversible_prob_block: 0.85
  compliance_prob_block: 0.15

escalation:
  enabled: true
  timeout_seconds: 30.0

proxy:
  upstream_servers:
    - name: "filesystem"
      command: ["npx", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
      env: {}
    # - name: "sqlite"
    #   command: ["mcp-server-sqlite", "--db-path", "./test.db"]
    #   env: {}
"""

    if output:
        with open(output, "w") as f:
            f.write(example_config)
        console.print(f"[green]Config written to {output}[/green]")
    else:
        console.print(example_config)


if __name__ == "__main__":
    app()


@app.command()
def validate_config(
    config_path: Annotated[str, typer.Argument(help="Path to config YAML file")],
) -> None:
    """Validate a configuration file."""
    try:
        config = load_config(config_path)
        console.print("[green]✓ Configuration is valid[/green]")
        console.print(f"  JEV model: {config.jev.model}")
        console.print(f"  JEV endpoint: {config.jev.endpoint}")
        console.print(f"  Upstream servers: {len(config.proxy.upstream_servers)}")
        for upstream in config.proxy.upstream_servers:
            console.print(f"    - {upstream.name}: {' '.join(upstream.command)}")
        console.print(f"  Policy: blast_radius_allow_max={config.policy.blast_radius_allow_max}")
        console.print(f"  Escalation: enabled={config.escalation.enabled}, timeout={config.escalation.timeout_seconds}s")
    except Exception as e:
        console.print(f"[red]✗ Invalid configuration: {e}[/red]")
        sys.exit(1)


@app.command()
def test_jev(
    config_path: Annotated[str | None, typer.Option("--config", "-c", help="Path to config YAML file")] = None,
    jev_api_key: Annotated[str | None, typer.Option("--jev-api-key", envvar="OPENCODE_API_KEY", help="OpenCode Zen JEV API key")] = None,
) -> None:
    """Test JEV API connectivity with a sample evaluation."""
    import asyncio
    from proxyveto.evaluator import EvaluationRequest, JEVClient, Environment
    from proxyveto.config import JEVConfig, load_config

    async def run_test() -> None:
        try:
            if config_path:
                config = load_config(config_path)
                jev_config = config.jev
            else:
                jev_config = JEVConfig(api_key=jev_api_key)

            if not jev_config.api_key:
                console.print("[red]Error: JEV API key required[/red]")
                sys.exit(1)

            console.print(f"[cyan]Testing JEV connection to {jev_config.endpoint}...[/cyan]")
            client = JEVClient(jev_config)
            async with client:
                # Test with a benign request
                request = EvaluationRequest(
                    tool_name="read_file",
                    arguments={"path": "/tmp/test.txt"},
                    declared_intent="Read a test file",
                    environment=Environment.LOCAL_FS,
                )
                console.print("Sending test evaluation...")
                context = await client.evaluate_with_retry(request)

                console.print("[green]✓ JEV evaluation successful[/green]")
                console.print(f"  Latency: {context.latency_ms:.0f}ms")
                console.print(f"  Irreversible: {context.response.is_irreversible.probability:.0%} ({context.response.is_irreversible.label})")
                console.print(f"  Blast Radius: {context.response.blast_radius.score}/5 ({context.response.blast_radius.label})")
                console.print(f"  Compliance: {context.response.policy_compliance.probability:.0%} ({context.response.policy_compliance.label})")

        except Exception as e:
            console.print(f"[red]✗ JEV test failed: {e}[/red]")
            sys.exit(1)

    asyncio.run(run_test())