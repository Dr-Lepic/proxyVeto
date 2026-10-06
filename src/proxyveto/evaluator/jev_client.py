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

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
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
                "/decisions",  # OpenCode Zen decisions endpoint
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
        # Based on OpenCode Zen API format for decisions endpoint
        return {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tool_name": request.tool_name,
                            "arguments": request.arguments,
                            "declared_intent": request.declared_intent,
                            "environment": request.environment.value,
                        }
                    ),
                }
            ],
            "temperature": 0.0,
            "max_tokens": 500,
        }

    def _parse_response(self, raw: dict[str, Any]) -> EvaluationResponse:
        """Parse OpenCode Zen JEV response into structured model."""
        # Expected response format from OpenCode Zen decisions endpoint:
        # {
        #   "choices": [{
        #     "message": {
        #       "content": "{\"is_irreversible\": {...}, \"blast_radius\": {...}, \"policy_compliance\": {...}}"
        #     }
        #   }]
        # }

        # Extract content from first choice
        choices = raw.get("choices", [])
        if not choices:
            raise JEVResponseError("No choices in JEV response")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content:
            raise JEVResponseError("Empty content in JEV response")

        # Parse JSON from content
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown code blocks
            import re

            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    raise JEVResponseError(f"Failed to parse JEV response JSON: {e}") from e
            else:
                raise JEVResponseError(f"Failed to parse JEV response JSON: {e}") from e

        # Validate required fields
        required = ["is_irreversible", "blast_radius", "policy_compliance"]
        for field in required:
            if field not in data:
                raise JEVResponseError(f"Missing required field in JEV response: {field}")

        return EvaluationResponse(
            is_irreversible=PrimitiveResult(**data["is_irreversible"]),
            blast_radius=PrimitiveResult(**data["blast_radius"]),
            policy_compliance=PrimitiveResult(**data["policy_compliance"]),
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