import pytest
from typer.testing import CliRunner

from proxyveto.cli import app


class TestCLI:
    def setup_method(self):
        self.runner = CliRunner()

    def test_config_command(self):
        result = self.runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "jev:" in result.output
        assert "policy:" in result.output
        assert "escalation:" in result.output
        assert "proxy:" in result.output

    def test_config_command_output_file(self, tmp_path):
        output_file = tmp_path / "config.yaml"
        result = self.runner.invoke(app, ["config", "--output", str(output_file)])
        assert result.exit_code == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "jev:" in content
        assert "policy:" in content

    def test_run_missing_upstream(self):
        result = self.runner.invoke(app, ["run", "--jev-api-key", "test-key"])
        assert result.exit_code == 1
        assert "No upstream servers configured" in result.output

    def test_run_missing_jev_key(self):
        result = self.runner.invoke(app, ["run", "--upstream", "echo", "--upstream", "test"])
        assert result.exit_code != 0  # Should fail
        assert "JEV API key required" in result.output

    def test_help(self):
        result = self.runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "ProxyVeto" in result.output
        assert "run" in result.output
        assert "config" in result.output