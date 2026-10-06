from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from proxyveto.evaluator import EvaluationResponse


class ActionStatus(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"


class PolicyConfig(BaseModel):
    blast_radius_allow_max: int = Field(default=2, ge=1, le=5)
    irreversible_prob_block: float = Field(default=0.85, ge=0.0, le=1.0)
    compliance_prob_block: float = Field(default=0.15, ge=0.0, le=1.0)


@dataclass
class Decision:
    action: ActionStatus
    reason: str
    details: dict


class PolicyEngine:
    """Maps JEV evaluation results to policy decisions."""

    def __init__(self, config: PolicyConfig):
        self.config = config

    def decide(self, evaluation_response: EvaluationResponse) -> Decision:
        """Evaluate JEV response and return policy decision."""
        blast_radius = evaluation_response.blast_radius.score or 3  # default to medium if not set
        irreversible_prob = evaluation_response.is_irreversible.probability
        compliance_prob = evaluation_response.policy_compliance.probability

        # BLOCK: high blast radius, highly irreversible, or non-compliant
        if (
            blast_radius >= 4
            or irreversible_prob > self.config.irreversible_prob_block
            or compliance_prob < self.config.compliance_prob_block
        ):
            return Decision(
                action=ActionStatus.BLOCK,
                reason=f"High risk: blast_radius={blast_radius}, irreversible={irreversible_prob:.2f}, compliance={compliance_prob:.2f}",
                details={
                    "blast_radius": blast_radius,
                    "irreversible_prob": irreversible_prob,
                    "compliance_prob": compliance_prob,
                },
            )

        # ALLOW: low blast radius, low irreversibility, high compliance
        if (
            blast_radius <= self.config.blast_radius_allow_max
            and irreversible_prob < 0.3  # low irreversibility threshold for ALLOW
            and compliance_prob > 0.7    # high compliance threshold for ALLOW
        ):
            return Decision(
                action=ActionStatus.ALLOW,
                reason=f"Low risk: blast_radius={blast_radius}, irreversible={irreversible_prob:.2f}, compliance={compliance_prob:.2f}",
                details={
                    "blast_radius": blast_radius,
                    "irreversible_prob": irreversible_prob,
                    "compliance_prob": compliance_prob,
                },
            )

        # ESCALATE: medium risk, needs human review
        return Decision(
            action=ActionStatus.ESCALATE,
            reason=f"Medium risk: blast_radius={blast_radius}, irreversible={irreversible_prob:.2f}, compliance={compliance_prob:.2f}",
            details={
                "blast_radius": blast_radius,
                "irreversible_prob": irreversible_prob,
                "compliance_prob": compliance_prob,
            },
        )