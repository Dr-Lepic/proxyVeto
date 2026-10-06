import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from proxyveto.proxy.transport import StdioTransport, MCPServerTransport
from proxyveto.proxy.server import ProxyServer, ToolCallInterceptor
from proxyveto.policy import Decision, ActionStatus, PolicyConfig, PolicyEngine
from proxyveto.evaluator import EvaluationContext, EvaluationResponse, PrimitiveResult, JEVPrimitive
from proxyveto.config import JEVConfig


class MockJEVClient:
    """Mock JEV client for testing."""

    def __init__(self, response: EvaluationResponse | None = None, should_raise: bool = False):
        self.response = response
        self.should_raise = should_raise

    async def evaluate_with_retry(self, request):
        if self.should_raise:
            from proxyveto.evaluator import JEVClientError
            raise JEVClientError("Test error")
        return EvaluationContext(
            request=request,
            response=self.response or self._default_response(),
            latency_ms=100.0,
        )

    def _default_response(self) -> EvaluationResponse:
        return EvaluationResponse(
            is_irreversible=PrimitiveResult(
                probability=0.2,
                label=False,
            ),
            blast_radius=PrimitiveResult(
                probability=0.3,
                label=2,
                score=2,
            ),
            policy_compliance=PrimitiveResult(
                probability=0.9,
                label=True,
            ),
        )


class MockEscalationHandler:
    """Mock escalation handler for testing."""

    def __init__(self, approve: bool = True):
        self.approve = approve

    async def escalate(self, decision, request_data):
        return self.approve


class TestStdioTransport:
    @pytest.mark.asyncio
    async def test_write_message(self):
        transport = StdioTransport()

        with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush") as mock_flush:
            with patch("sys.stdin.isatty", return_value=False):
                with patch("asyncio.get_event_loop") as mock_loop:
                    mock_loop.return_value.connect_read_pipe = AsyncMock()
                    await transport.write_message({"jsonrpc": "2.0", "method": "test", "id": 1})
                    mock_write.assert_called_once()
                    mock_flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self):
        transport = StdioTransport()
        # Should not raise
        await transport.close()


class TestToolCallInterceptor:
    @pytest.fixture
    def mock_components(self):
        jev_client = MockJEVClient()
        policy_engine = PolicyEngine(PolicyConfig())
        escalation_handler = MockEscalationHandler(approve=True)
        return jev_client, policy_engine, escalation_handler

    @pytest.mark.asyncio
    async def test_intercept_allow(self, mock_components):
        jev_client, policy_engine, escalation_handler = mock_components
        interceptor = ToolCallInterceptor(jev_client, policy_engine, escalation_handler)

        decision = await interceptor.intercept("safe_tool", {"arg": "value"})
        assert decision.action == ActionStatus.ALLOW

    @pytest.mark.asyncio
    async def test_intercept_block_high_blast_radius(self, mock_components):
        jev_client, policy_engine, escalation_handler = mock_components
        # Override with high blast radius
        jev_client.response = EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=0.2, label=False),
            blast_radius=PrimitiveResult(probability=0.8, label=5, score=5),
            policy_compliance=PrimitiveResult(probability=0.9, label=True),
        )
        interceptor = ToolCallInterceptor(jev_client, policy_engine, escalation_handler)

        decision = await interceptor.intercept("dangerous_tool", {"arg": "value"})
        assert decision.action == ActionStatus.BLOCK

    @pytest.mark.asyncio
    async def test_intercept_escalate_approved(self, mock_components):
        jev_client, policy_engine, escalation_handler = mock_components
        # Override with medium risk
        jev_client.response = EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=0.5, label=False),
            blast_radius=PrimitiveResult(probability=0.5, label=3, score=3),
            policy_compliance=PrimitiveResult(probability=0.6, label=True),
        )
        interceptor = ToolCallInterceptor(jev_client, policy_engine, escalation_handler)

        decision = await interceptor.intercept("medium_tool", {"arg": "value"})
        assert decision.action == ActionStatus.ESCALATE
        assert decision.details.get("human_approved") is True

    @pytest.mark.asyncio
    async def test_intercept_escalate_denied(self, mock_components):
        jev_client, policy_engine, _ = mock_components
        escalation_handler = MockEscalationHandler(approve=False)
        # Override with medium risk
        jev_client.response = EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=0.5, label=False),
            blast_radius=PrimitiveResult(probability=0.5, label=3, score=3),
            policy_compliance=PrimitiveResult(probability=0.6, label=True),
        )
        interceptor = ToolCallInterceptor(jev_client, policy_engine, escalation_handler)

        decision = await interceptor.intercept("medium_tool", {"arg": "value"})
        assert decision.action == ActionStatus.ESCALATE
        assert decision.details.get("human_approved") is False

    @pytest.mark.asyncio
    async def test_intercept_jev_error(self, mock_components):
        jev_client, policy_engine, escalation_handler = mock_components
        jev_client.should_raise = True
        interceptor = ToolCallInterceptor(jev_client, policy_engine, escalation_handler)

        decision = await interceptor.intercept("error_tool", {"arg": "value"})
        assert decision.action == ActionStatus.ESCALATE
        assert "JEV evaluation failed" in decision.reason


class TestProxyServer:
    @pytest.fixture
    def config(self):
        from proxyveto.config import Config, ProxyConfig, UpstreamServerConfig, JEVConfig, PolicyConfig, EscalationConfig

        return Config(
            jev=JEVConfig(api_key="test"),
            policy=PolicyConfig(),
            escalation=EscalationConfig(enabled=False),
            proxy=ProxyConfig(
                upstream_servers=[
                    UpstreamServerConfig(name="test", command=["echo", "test"])
                ]
            ),
        )

    @pytest.mark.asyncio
    async def test_start_stop(self, config):
        with patch.object(MCPServerTransport, 'start', new_callable=AsyncMock) as mock_start:
            with patch.object(MCPServerTransport, 'close', new_callable=AsyncMock) as mock_close:
                with patch.object(StdioTransport, 'read_message', new_callable=AsyncMock, return_value=None) as mock_read:
                    server = ProxyServer(config)
                    # Run start in background and stop quickly
                    task = asyncio.create_task(server.start())
                    await asyncio.sleep(0.1)
                    await server.stop()
                    await task

                    mock_start.assert_called_once()
                    mock_close.assert_called_once()
                    mock_read.assert_called()