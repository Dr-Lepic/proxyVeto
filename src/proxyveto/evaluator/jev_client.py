from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import structlog

from proxyveto.config import JEVConfig
from proxyveto.evaluator.schema import (
    Environment,
    EvaluationContext,
    EvaluationRequest,
    EvaluationResponse,
    PrimitiveResult,
)

logger = structlog.get_logger(__name__)


class JEVClientError(Exception):
    """Base exception for JEV client errors."""

    pass


class JEVTimeoutError(JEVClientError):
    """JEV request timed out."""

    pass


class JEVResponseError(JEVClientError):
    """JEV returned an error or invalid response."""

    pass


class JEVClient:
    """Async client for calling JEV via OpenCode Zen API."""

    def __init__(self, config: JEVConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> JEVClient:
        self._client = httpx.AsyncClient(
            base_url=self.config.endpoint,
            timeout=httpx.Timeout(self.config.timeout_seconds),
            headers=self._build_headers(),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def evaluate(self, request: EvaluationRequest) -> EvaluationContext:
        """Evaluate a tool call via JEV."""
        start_time = time.perf_counter()

        payload = self._build_payload(request)

        try:
            assert self._client is not None, "Client not initialized"
            response = await self._client.post(
                "/systemone",  # OpenCode Zen System One endpoint
                json=payload,
            )
            response.raise_for_status()
            raw_response = response.json()

        except httpx.TimeoutException as e:
            logger.error("jev_request_timeout", error=str(e))
            raise JEVTimeoutError(f"JEV request timed out after {self.config.timeout_seconds}s") from e
        except httpx.HTTPStatusError as e:
            logger.error("jev_http_error", status=e.response.status_code, body=e.response.text)
            raise JEVResponseError(f"JEV HTTP {e.response.status_code}: {e.response.text}") from e
        except Exception as e:
            logger.error("jev_request_failed", error=str(e))
            raise JEVClientError(f"JEV request failed: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        try:
            evaluation_response = self._parse_response(raw_response)
        except Exception as e:
            logger.error("jev_response_parse_failed", error=str(e), raw=raw_response)
            raise JEVResponseError(f"Failed to parse JEV response: {e}") from e

        logger.info(
            "jev_evaluation_complete",
            tool_name=request.tool_name,
            latency_ms=latency_ms,
            is_irreversible=evaluation_response.is_irreversible.probability,
            blast_radius=evaluation_response.blast_radius.score,
            policy_compliance=evaluation_response.policy_compliance.probability,
        )

        return EvaluationContext(
            request=request,
            response=evaluation_response,
            latency_ms=latency_ms,
            raw_response=raw_response,
        )

    def _build_payload(self, request: EvaluationRequest) -> dict[str, Any]:
        """Build the request payload for OpenCode Zen JEV endpoint."""
        # Based on OpenCode Zen System One API format:
        # {
        #   "model": "jev-1.13-free",
        #   "state": "Tool call: execute_shell_command with args {...} and intent: List files",
        #   "questions": {
        #     "is_irreversible": {"type": "noul", "instructions": "Is this tool call irreversible?"},
        #     "blast_radius": {"type": "choice", "instructions": "What is the blast radius?", "criteria": {"1": "read-only local", "2": "local write", "3": "network read", "4": "network write", "5": "destructive/credential exfiltration"}},
        #     "policy_compliance": {"type": "noul", "instructions": "Does this comply with security policy?"}
        #   }
        # }
        state = f"Tool call: {request.tool_name} with args {json.dumps(request.arguments)} and intent: {request.declared_intent} (environment: {request.environment.value})"
        
        return {
            "model": self.config.model,
            "state": state,
            "questions": {
                "is_irreversible": {
                    "type": "noul",
                    "instructions": "Is this tool call irreversible? i.e., can the action be undone or rolled back?"
                },
                "blast_radius": {
                    "type": "choice",
                    "instructions": "What is the blast radius of this tool call?",
                    "criteria": {
                        "1": "read-only local (e.g., read file, list directory)",
                        "2": "local write (e.g., write file, create directory)",
                        "3": "network read (e.g., HTTP GET, DNS query)",
                        "4": "network write (e.g., POST, PUT, DELETE, API call with side effects)",
                        "5": "destructive/credential exfiltration (e.g., rm -rf, format disk, send secrets)"
                    }
                },
                "policy_compliance": {
                    "type": "noul",
                    "instructions": "Does this tool call comply with security policy? Is it safe and authorized?"
                }
            }
        }

    def _parse_response(self, raw: dict[str, Any]) -> EvaluationResponse:
        """Parse OpenCode Zen JEV response into structured model."""
        # Expected response format from OpenCode Zen System One endpoint:
        # {
        #   "answers": {
        #     "is_irreversible": {"value": true/false, "probability": 0.0-1.0, "confidence": 0.0-1.0},
        #     "blast_radius": {"value": "1"|"2"|"3"|"4"|"5", "probabilities": {"1": 0.1, "2": 0.2, ...}, "confidence": 0.0-1.0},
        #     "policy_compliance": {"value": true/false, "probability": 0.0-1.0, "confidence": 0.0-1.0}
        #   }
        # }

        answers = raw.get("answers", {})
        if not answers:
            raise JEVResponseError("No answers in JEV response")

        # Parse is_irreversible (noul - yes/no with probability)
        irr = answers.get("is_irreversible", {})
        if not irr:
            raise JEVResponseError("Missing is_irreversible in JEV response")
        is_irreversible = PrimitiveResult(
            label="yes" if irr.get("value") else "no",
            probability=float(irr.get("probability", 0.0)),
        )

        # Parse blast_radius (choice - single value with probabilities per option)
        br = answers.get("blast_radius", {})
        if not br:
            raise JEVResponseError("Missing blast_radius in JEV response")
        # Get the score from the chosen value
        try:
            score = int(br.get("value", "1"))
        except (ValueError, TypeError):
            score = 1
        blast_radius = PrimitiveResult(
            label=str(score),
            probability=float(max(br.get("probabilities", {}).values(), default=0.0)),
            score=score,
        )

        # Parse policy_compliance (noul)
        pc = answers.get("policy_compliance", {})
        if not pc:
            raise JEVResponseError("Missing policy_compliance in JEV response")
        policy_compliance = PrimitiveResult(
            label="yes" if pc.get("value") else "no",
            probability=float(pc.get("probability", 0.0)),
        )

        return EvaluationResponse(
            is_irreversible=is_irreversible,
            blast_radius=blast_radius,
            policy_compliance=policy_compliance,
        )

    async def evaluate_with_retry(
        self,
        request: EvaluationRequest,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> EvaluationContext:
        """Evaluate with exponential backoff retry."""
        last_error = None

        for attempt in range(max_retries):
            try:
                return await self.evaluate(request)
            except (JEVTimeoutError, JEVResponseError, httpx.RequestError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "jev_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("jev_max_retries_exceeded", error=str(e))

        raise JEVClientError(f"JEV evaluation failed after {max_retries} retries: {last_error}") from last_error