from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Environment(str, Enum):
    LOCAL_FS = "local_fs"
    SANDBOX = "sandbox"
    PROD = "prod"
    STAGING = "staging"
    CI = "ci"


class JEVPrimitive(str, Enum):
    IS_IRREVERSIBLE = "is_irreversible"
    BLAST_RADIUS = "blast_radius"
    POLICY_COMPLIANCE = "policy_compliance"


class EvaluationRequest(BaseModel):
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any]
    declared_intent: str = Field(..., min_length=1)
    environment: Environment = Environment.LOCAL_FS

    @field_validator("arguments", mode="before")
    @classmethod
    def _ensure_dict(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            return {"value": v}
        return v


class PrimitiveResult(BaseModel):
    probability: float = Field(..., ge=0.0, le=1.0)
    label: bool | int | str | None = None
    score: int | None = None  # for blast_radius 1-5

    @property
    def is_true(self) -> bool:
        if isinstance(self.label, bool):
            return self.label
        if isinstance(self.label, (int, str)):
            return bool(self.label)
        return self.probability > 0.5


class EvaluationResponse(BaseModel):
    is_irreversible: PrimitiveResult
    blast_radius: PrimitiveResult
    policy_compliance: PrimitiveResult

    def get_primitive(self, primitive: JEVPrimitive) -> PrimitiveResult:
        return getattr(self, primitive.value)  # type: ignore[no-any-return]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_irreversible": {
                "probability": self.is_irreversible.probability,
                "label": self.is_irreversible.label,
            },
            "blast_radius": {
                "score": self.blast_radius.score,
                "label": self.blast_radius.label,
                "probability": self.blast_radius.probability,
            },
            "policy_compliance": {
                "probability": self.policy_compliance.probability,
                "label": self.policy_compliance.label,
            },
        }


@dataclass
class EvaluationContext:
    request: EvaluationRequest
    response: EvaluationResponse
    latency_ms: float
    raw_response: dict[str, Any] | None = None