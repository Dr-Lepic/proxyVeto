import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from proxyveto.escalation.terminal import TerminalEscalation, MockEscalation, create_escalation_handler
from proxyveto.policy.engine import Decision, ActionStatus


class TestMockEscalation:
    @pytest.mark.asyncio
    async def test_mock_allow(self):
        handler = MockEscalation(auto_allow=True)
        decision = Decision(action=ActionStatus.ESCALATE, reason="test", details={})
        result = await handler.escalate(decision, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_mock_block(self):
        handler = MockEscalation(auto_allow=False)
        decision = Decision(action=ActionStatus.ESCALATE, reason="test", details={})
        result = await handler.escalate(decision, {})
        assert result is False


class TestCreateEscalationHandler:
    def test_create_mock(self):
        handler = create_escalation_handler(enabled=False, mock=True)
        assert isinstance(handler, MockEscalation)
        assert handler.auto_allow is True

    def test_create_terminal(self):
        handler = create_escalation_handler(enabled=True, mock=False)
        assert isinstance(handler, TerminalEscalation)

    def test_create_disabled(self):
        handler = create_escalation_handler(enabled=False, mock=False)
        assert isinstance(handler, MockEscalation)
        assert handler.auto_allow is False


class TestTerminalEscalation:
    @pytest.mark.asyncio
    async def test_escalate_yes(self):
        handler = TerminalEscalation(timeout_seconds=1.0)
        decision = Decision(
            action=ActionStatus.ESCALATE,
            reason="Test reason",
            details={"blast_radius": 3, "irreversible_prob": 0.5, "compliance_prob": 0.5},
        )
        request_data = {
            "tool_name": "test_tool",
            "arguments": {"arg1": "value1"},
            "declared_intent": "Test intent",
            "environment": "local_fs",
        }

        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", return_value="y\n"):
                result = await handler.escalate(decision, request_data)
                assert result is True

    @pytest.mark.asyncio
    async def test_escalate_no(self):
        handler = TerminalEscalation(timeout_seconds=1.0)
        decision = Decision(action=ActionStatus.ESCALATE, reason="test", details={})
        request_data = {"tool_name": "test", "arguments": {}, "declared_intent": "test", "environment": "local_fs"}

        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", return_value="n\n"):
                result = await handler.escalate(decision, request_data)
                assert result is False

    @pytest.mark.asyncio
    async def test_escalate_no_tty(self):
        handler = TerminalEscalation(timeout_seconds=1.0)
        decision = Decision(action=ActionStatus.ESCALATE, reason="test", details={})
        request_data = {"tool_name": "test", "arguments": {}, "declared_intent": "test", "environment": "local_fs"}

        with patch("sys.stdin.isatty", return_value=False):
            result = await handler.escalate(decision, request_data)
            assert result is False