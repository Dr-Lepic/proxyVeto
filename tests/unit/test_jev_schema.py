import pytest

from proxyveto.evaluator.schema import (
    Environment,
    EvaluationRequest,
    EvaluationResponse,
    PrimitiveResult,
)


class TestPrimitiveResult:
    def test_is_true_with_boolean_label(self):
        pr = PrimitiveResult(probability=0.8, label=True)
        assert pr.is_true is True

        pr = PrimitiveResult(probability=0.8, label=False)
        assert pr.is_true is False

    def test_is_true_with_int_label(self):
        pr = PrimitiveResult(probability=0.8, label=1)
        assert pr.is_true is True

        pr = PrimitiveResult(probability=0.8, label=0)
        assert pr.is_true is False

    def test_is_true_with_string_label(self):
        pr = PrimitiveResult(probability=0.8, label="true")
        assert pr.is_true is True

        pr = PrimitiveResult(probability=0.8, label="false")
        assert pr.is_true is True  # non-empty string is truthy

    def test_is_true_fallback_to_probability(self):
        pr = PrimitiveResult(probability=0.8, label=None)
        assert pr.is_true is True

        pr = PrimitiveResult(probability=0.3, label=None)
        assert pr.is_true is False


class TestEvaluationRequest:
    def test_valid_request(self):
        req = EvaluationRequest(
            tool_name="execute_shell_command",
            arguments={"command": "ls -la"},
            declared_intent="List files",
            environment=Environment.LOCAL_FS,
        )
        assert req.tool_name == "execute_shell_command"
        assert req.environment == Environment.LOCAL_FS

    def test_arguments_none_becomes_empty_dict(self):
        req = EvaluationRequest(
            tool_name="test",
            arguments=None,
            declared_intent="test",
        )
        assert req.arguments == {}

    def test_arguments_non_dict_wrapped(self):
        req = EvaluationRequest(
            tool_name="test",
            arguments="raw_value",
            declared_intent="test",
        )
        assert req.arguments == {"value": "raw_value"}


class TestEvaluationResponse:
    def test_get_primitive(self):
        from proxyveto.evaluator.schema import JEVPrimitive

        resp = EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=0.9, label=True),
            blast_radius=PrimitiveResult(probability=0.8, score=4, label="high"),
            policy_compliance=PrimitiveResult(probability=0.2, label=False),
        )

        irr = resp.get_primitive(JEVPrimitive.IS_IRREVERSIBLE)
        assert irr.probability == 0.9

        blast = resp.get_primitive(JEVPrimitive.BLAST_RADIUS)
        assert blast.score == 4

        comp = resp.get_primitive(JEVPrimitive.POLICY_COMPLIANCE)
        assert comp.probability == 0.2

    def test_to_dict(self):
        resp = EvaluationResponse(
            is_irreversible=PrimitiveResult(probability=0.9, label=True),
            blast_radius=PrimitiveResult(probability=0.8, score=4, label="high"),
            policy_compliance=PrimitiveResult(probability=0.2, label=False),
        )

        d = resp.to_dict()
        assert d["is_irreversible"]["probability"] == 0.9
        assert d["is_irreversible"]["label"] is True
        assert d["blast_radius"]["score"] == 4
        assert d["policy_compliance"]["probability"] == 0.2


class TestEnvironment:
    def test_enum_values(self):
        assert Environment.LOCAL_FS == "local_fs"
        assert Environment.SANDBOX == "sandbox"
        assert Environment.PROD == "prod"
        assert Environment.STAGING == "staging"
        assert Environment.CI == "ci"