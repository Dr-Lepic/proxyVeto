from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from proxyveto.config import Config, UpstreamServerConfig
from proxyveto.evaluator import Environment, EvaluationRequest, JEVClient, JEVClientError
from proxyveto.escalation import create_escalation_handler
from proxyveto.policy import Decision, PolicyEngine, ActionStatus, PolicyConfig
from proxyveto.proxy.transport import MCPServerTransport, StdioTransport, Transport

logger = structlog.get_logger(__name__)


class ToolCallInterceptor:
    """Intercepts and evaluates tool calls via JEV."""

    def __init__(
        self,
        jev_client: JEVClient,
        policy_engine: PolicyEngine,
        escalation_handler,
        environment: str = "local_fs",
    ):
        self.jev_client = jev_client
        self.policy_engine = policy_engine
        self.escalation_handler = escalation_handler
        self.environment = environment

    async def intercept(self, tool_name: str, arguments: dict[str, Any], declared_intent: str | None = None) -> Decision:
        """Intercept a tool call, evaluate via JEV, and return policy decision."""
        intent = declared_intent or f"Agent requested to call {tool_name}"

        request = EvaluationRequest(
            tool_name=tool_name,
            arguments=arguments,
            declared_intent=intent,
            environment=Environment(self.environment),
        )

        try:
            context = await self.jev_client.evaluate_with_retry(request)
            decision = self.policy_engine.decide(context.response)

            # Handle escalation
            if decision.action == ActionStatus.ESCALATE:
                request_data = {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "declared_intent": intent,
                    "environment": self.environment,
                }
                approved = await self.escalation_handler.escalate(decision, request_data)
                if approved:
                    return Decision(
                        action=ActionStatus.ESCALATE,
                        reason=decision.reason + " (human approved)",
                        details={**decision.details, "human_approved": True},
                    )
                else:
                    return Decision(
                        action=ActionStatus.ESCALATE,
                        reason=decision.reason + " (human denied)",
                        details={**decision.details, "human_approved": False},
                    )

            return decision

        except JEVClientError as e:
            logger.error("interceptor_jev_error", error=str(e), tool_name=tool_name)
            # On JEV error, escalate for safety
            return Decision(
                action=ActionStatus.ESCALATE,
                reason=f"JEV evaluation failed: {e}",
                details={"error": str(e)},
            )


class ProxyServer:
    """MCP proxy server that intercepts tools/call requests."""

    def __init__(self, config: Config):
        self.config = config
        self.client_transport: StdioTransport | None = None
        self.upstream_transports: dict[str, MCPServerTransport] = {}
        self.interceptor: ToolCallInterceptor | None = None
        self._pending_requests: dict[str | int, asyncio.Future] = {}
        self._running = False

    async def start(self) -> None:
        """Start the proxy server."""
        self._running = True

        # Initialize client transport (stdio for MVP)
        self.client_transport = StdioTransport()

        # Initialize upstream transports
        for upstream_config in self.config.proxy.upstream_servers:
            transport = MCPServerTransport(upstream_config.command, upstream_config.env)
            await transport.start()
            self.upstream_transports[upstream_config.name] = transport

        # Initialize interceptor
        jev_client = JEVClient(self.config.jev)
        policy_engine = PolicyEngine(PolicyConfig(
            blast_radius_allow_max=self.config.policy.blast_radius_allow_max,
            irreversible_prob_block=self.config.policy.irreversible_prob_block,
            compliance_prob_block=self.config.policy.compliance_prob_block,
        ))
        escalation_handler = create_escalation_handler(
            enabled=self.config.escalation.enabled,
            timeout_seconds=self.config.escalation.timeout_seconds,
        )
        self.interceptor = ToolCallInterceptor(
            jev_client=jev_client,
            policy_engine=policy_engine,
            escalation_handler=escalation_handler,
            environment=self.config.proxy.upstream_servers[0].name if self.config.proxy.upstream_servers else "local_fs",
        )

        logger.info("proxy_server_started", upstreams=list(self.upstream_transports.keys()))

        # Start message processing loop
        await self._run()

    async def _run(self) -> None:
        """Main message processing loop."""
        assert self.client_transport is not None

        while self._running:
            try:
                message = await self.client_transport.read_message()
                if message is None:
                    logger.info("client_disconnected")
                    break

                await self._handle_client_message(message)

            except Exception as e:
                logger.error("proxy_loop_error", error=str(e))
                if not self._running:
                    break

    async def _handle_client_message(self, message: dict[str, Any]) -> None:
        """Handle incoming message from client."""
        method = message.get("method")
        msg_id = message.get("id")

        # Handle requests (have id)
        if msg_id is not None and method:
            if method == "tools/call":
                await self._handle_tool_call(message)
            else:
                # Forward other requests to upstream
                await self._forward_to_upstream(message)
        # Handle notifications (no id)
        elif method:
            # Forward notifications to upstream
            await self._forward_to_upstream(message)
        # Handle responses (have id, no method)
        elif msg_id is not None:
            await self._handle_upstream_response(message)

    async def _handle_tool_call(self, message: dict[str, Any]) -> None:
        """Intercept and evaluate tools/call request."""
        msg_id = message.get("id")
        params = message.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        logger.info("tool_call_intercepted", tool_name=tool_name, msg_id=msg_id)

        # Evaluate via JEV
        decision = await self.interceptor.intercept(tool_name, arguments)

        if decision.action == ActionStatus.ALLOW:
            logger.info("tool_call_allowed", tool_name=tool_name, reason=decision.reason)
            await self._forward_to_upstream(message)
        elif decision.action == ActionStatus.BLOCK:
            logger.warning("tool_call_blocked", tool_name=tool_name, reason=decision.reason)
            await self._send_error_response(msg_id, f"Blocked by policy: {decision.reason}")
        else:  # ESCALATE - already handled in interceptor
            human_approved = decision.details.get("human_approved", False)
            if human_approved:
                logger.info("tool_call_approved_via_escalation", tool_name=tool_name)
                await self._forward_to_upstream(message)
            else:
                logger.warning("tool_call_denied_via_escalation", tool_name=tool_name)
                await self._send_error_response(msg_id, f"Denied by human: {decision.reason}")

    async def _forward_to_upstream(self, message: dict[str, Any]) -> None:
        """Forward message to appropriate upstream server."""
        # For MVP, forward to first upstream server
        if not self.upstream_transports:
            logger.warning("no_upstream_servers")
            return

        # Use first upstream for now
        upstream = next(iter(self.upstream_transports.values()))
        await upstream.write_message(message)

    async def _handle_upstream_response(self, message: dict[str, Any]) -> None:
        """Handle response from upstream server."""
        msg_id = message.get("id")
        # Forward response back to client
        await self.client_transport.write_message(message)

    async def _send_error_response(self, msg_id: str | int, error_message: str) -> None:
        """Send JSON-RPC error response to client."""
        error_response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32603,
                "message": error_message,
            },
        }
        await self.client_transport.write_message(error_response)

    async def stop(self) -> None:
        """Stop the proxy server."""
        self._running = False

        for transport in self.upstream_transports.values():
            await transport.close()

        if self.client_transport:
            await self.client_transport.close()

        logger.info("proxy_server_stopped")