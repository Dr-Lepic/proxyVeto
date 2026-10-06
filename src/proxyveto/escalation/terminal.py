from __future__ import annotations

import asyncio
import sys
from typing import Any

import structlog

from proxyveto.policy.engine import Decision

logger = structlog.get_logger(__name__)


class TerminalEscalation:
    """Terminal-based human-in-the-loop escalation handler."""

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds

    async def escalate(self, decision: Decision, request_data: dict[str, Any]) -> bool:
        """
        Present the escalation to the user via terminal and return their decision.

        Returns:
            True if user approves (allow), False if user denies (block)
        """
        if not sys.stdin.isatty():
            logger.warning("escalation_no_tty", detail="No TTY available, auto-blocking")
            return False

        # Print escalation details
        self._print_escalation(decision, request_data)

        # Wait for user input with timeout
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, self._get_user_input),
                timeout=self.timeout_seconds,
            )
            return self._parse_response(response)
        except asyncio.TimeoutError:
            logger.warning("escalation_timeout", timeout=self.timeout_seconds)
            print(f"\n⏱️  Timeout ({self.timeout_seconds}s) — auto-blocking")
            return False
        except (EOFError, KeyboardInterrupt):
            logger.warning("escalation_interrupted")
            print("\n❌ Interrupted — auto-blocking")
            return False

    def _print_escalation(self, decision: Decision, request_data: dict[str, Any]) -> None:
        """Print formatted escalation prompt."""
        print("\n" + "=" * 60)
        print("🚨  PROXYVETO ESCALATION — Human Review Required")
        print("=" * 60)

        tool_name = request_data.get("tool_name", "unknown")
        arguments = request_data.get("arguments", {})
        intent = request_data.get("declared_intent", "No intent provided")
        environment = request_data.get("environment", "unknown")

        print(f"\n🔧 Tool: {tool_name}")
        print(f"📝 Intent: {intent}")
        print(f"🌍 Environment: {environment}")
        print(f"\n📋 Arguments:")
        for key, value in arguments.items():
            print(f"   {key}: {value}")

        details = decision.details
        print(f"\n📊 JEV Assessment:")
        print(f"   Blast Radius: {details.get('blast_radius', 'N/A')}/5")
        print(f"   Irreversible: {details.get('irreversible_prob', 0):.0%}")
        print(f"   Compliance: {details.get('compliance_prob', 0):.0%}")

        print(f"\n⚖️  Policy Decision: {decision.action.value.upper()}")
        print(f"   Reason: {decision.reason}")

        print("\n" + "-" * 60)
        print("Allow this tool call? [y/N]: ", end="", flush=True)

    def _get_user_input(self) -> str:
        """Get user input (blocking)."""
        return sys.stdin.readline().strip()

    def _parse_response(self, response: str) -> bool:
        """Parse user response into boolean."""
        response = response.strip().lower()
        return response in ("y", "yes", "true", "1")


class MockEscalation:
    """Mock escalation handler for testing (always allows)."""

    def __init__(self, auto_allow: bool = True):
        self.auto_allow = auto_allow

    async def escalate(self, decision: Decision, request_data: dict[str, Any]) -> bool:
        logger.info("mock_escalation", action=decision.action.value, auto_allow=self.auto_allow)
        return self.auto_allow


def create_escalation_handler(enabled: bool, timeout_seconds: float = 30.0, mock: bool = False) -> TerminalEscalation | MockEscalation:
    """Factory for creating escalation handler based on config."""
    if mock:
        return MockEscalation(auto_allow=True)
    if enabled:
        return TerminalEscalation(timeout_seconds=timeout_seconds)
    return MockEscalation(auto_allow=False)  # disabled = auto-block