import pytest

from proxyveto.evaluator.schema import EvaluationResponse, PrimitiveResult
from proxyveto.policy.engine import ActionStatus, Decision, PolicyConfig, PolicyEngine


class TestPolicyEngine:
    def setup_method(self):
        self.config = PolicyConfig(
            blast_radius_allow_max=2,
            irreversible_prob_block=0.85,
            compliance_prob_block=0.15,
        )
        self.engine = PolicyEngine(self.config)

    def _make_response(
        self,
        blast_radius: int = 1,
        irreversible_prob: float = 0.1,
        compliance_prob: float = 0.9,
    ) -> EvaluationResponse:
        return EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=irreversible_prob, label=irreversible_prob > 0.5),
            blast_radius=PrimitiveResult(probability=0.5, score=blast_radius, label=str(blast_radius)),
            policy_compliance=PrimitiveResult(probability=compliance_prob, label=compliance_prob > 0.5),
        )

    def test_allow_low_risk(self):
        resp = self._make_response(blast_radius=1, irreversible_prob=0.1, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.ALLOW
        assert "Low risk" in decision.reason

    def test_allow_boundary_blast_radius(self):
        resp = self._make_response(blast_radius=2, irreversible_prob=0.1, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.ALLOW

    def test_block_high_blast_radius(self):
        resp = self._make_response(blast_radius=4, irreversible_prob=0.1, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.BLOCK
        assert "High risk" in decision.reason

    def test_block_high_blast_radius_5(self):
        resp = self._make_response(blast_radius=5, irreversible_prob=0.1, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.BLOCK

    def test_block_high_irreversible(self):
        resp = self._make_response(blast_radius=1, irreversible_prob=0.9, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.BLOCK

    def test_block_low_compliance(self):
        resp = self._make_response(blast_radius=1, irreversible_prob=0.1, compliance_prob=0.1)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.BLOCK

    def test_escalate_medium_blast_radius(self):
        resp = self._make_response(blast_radius=3, irreversible_prob=0.5, compliance_prob=0.5)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.ESCALATE
        assert "Medium risk" in decision.reason

    def test_escalate_high_irreversible_but_not_block_threshold(self):
        # irreversible_prob = 0.80 < 0.85 block threshold, but > allow threshold
        resp = self._make_response(blast_radius=2, irreversible_prob=0.80, compliance_prob=0.9)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.ESCALATE

    def test_escalate_low_compliance_but_not_block_threshold(self):
        # compliance_prob = 0.20 > 0.15 block threshold, but < allow threshold
        resp = self._make_response(blast_radius=2, irreversible_prob=0.1, compliance_prob=0.20)
        decision = self.engine.decide(resp)
        assert decision.action == ActionStatus.ESCALATE

    def test_custom_config_thresholds(self):
        custom_config = PolicyConfig(
            blast_radius_allow_max=3,
            irreversible_prob_block=0.90,
            compliance_prob_block=0.10,
        )
        custom_engine = PolicyEngine(custom_config)

        # blast_radius=3 should now be ALLOW with custom config
        resp = self._make_response(blast_radius=3, irreversible_prob=0.1, compliance_prob=0.9)
        decision = custom_engine.decide(resp)
        assert decision.action == ActionStatus.ALLOW

    def test_decision_details_contain_scores(self):
        resp = self._make_response(blast_radius=2, irreversible_prob=0.3, compliance_prob=0.8)
        decision = self.engine.decide(resp)
        assert "blast_radius" in decision.details
        assert "irreversible_prob" in decision.details
        assert "compliance_prob" in decision.details
        assert decision.details["blast_radius"] == 2
        assert decision.details["irreversible_prob"] == 0.3
        assert decision.details["compliance_prob"] == 0.8