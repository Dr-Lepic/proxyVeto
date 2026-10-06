"""
ProxyVeto - MCP Proxy Server with JEV-based Tool Call Interception

A standalone MCP proxy that intercepts tools/call requests, evaluates them via
JEV (via OpenCode Zen API) for safety/intent, and allows/blocks/escalates
to human-in-the-loop.
"""

from proxyveto.config import Config, load_config
from proxyveto.evaluator import (
    Environment,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationContext,
    JEVPrimitive,
    PrimitiveResult,
    JEVClient,
    JEVClientError,
)
from proxyveto.policy import ActionStatus, PolicyConfig, PolicyEngine, Decision
from proxyveto.escalation import (
    TerminalEscalation,
    MockEscalation,
    create_escalation_handler,
)
from proxyveto.proxy import (
    Transport,
    StdioTransport,
    MCPServerTransport,
    ProxyServer,
    ToolCallInterceptor,
)

__version__ = "0.1.0"

__all__ = [
    # Config
    "Config",
    "load_config",
    # Evaluator
    "Environment",
    "EvaluationRequest",
    "EvaluationResponse",
    "EvaluationContext",
    "JEVPrimitive",
    "PrimitiveResult",
    "JEVClient",
    "JEVClientError",
    # Policy
    "ActionStatus",
    "PolicyConfig",
    "PolicyEngine",
    "Decision",
    # Escalation
    "TerminalEscalation",
    "MockEscalation",
    "create_escalation_handler",
    # Proxy
    "Transport",
    "StdioTransport",
    "MCPServerTransport",
    "ProxyServer",
    "ToolCallInterceptor",
]