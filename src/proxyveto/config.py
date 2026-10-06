from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class JEVConfig(BaseSettings):
    endpoint: str = "https://opencode.ai/zen/v1"
    model: str = "jev-1.13-free"
    timeout_seconds: float = 5.0
    max_retries: int = 2
    api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_prefix="OPENCODE_", extra="ignore")


class PolicyConfig(BaseSettings):
    blast_radius_allow_max: int = Field(default=2, ge=1, le=5)
    irreversible_prob_block: float = Field(default=0.85, ge=0.0, le=1.0)
    compliance_prob_block: float = Field(default=0.15, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(env_prefix="POLICY_", extra="ignore")


class UpstreamServerConfig(BaseSettings):
    name: str
    command: list[str]
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    model_config = SettingsConfigDict(extra="ignore")


class ProxyConfig(BaseSettings):
    transport: str = Field(default="stdio", pattern="^(stdio|sse)$")
    host: str = "127.0.0.1"
    port: int = 8080
    upstream_servers: list[UpstreamServerConfig] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_prefix="PROXY_", extra="ignore")


class EscalationConfig(BaseSettings):
    enabled: bool = True
    timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(env_prefix="ESCALATION_", extra="ignore")


class LoggingConfig(BaseSettings):
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    format: str = Field(default="json", pattern="^(json|console)$")

    model_config = SettingsConfigDict(env_prefix="LOG_", extra="ignore")


class Config(BaseSettings):
    jev: JEVConfig = Field(default_factory=JEVConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    @field_validator("jev", mode="before")
    @classmethod
    def _resolve_jev_api_key(cls, v: Any) -> Any:
        if isinstance(v, dict) and "api_key" not in v:
            v["api_key"] = os.getenv("OPENCODE_API_KEY")
        return v


def load_config(path: str | Path) -> Config:
    """Load configuration from YAML file."""
    return Config.from_yaml(path)