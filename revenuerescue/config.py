"""Runtime configuration and production-readiness validation."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    api_token: str
    cron_secret: str
    database_url: str
    scrapling_enabled: bool
    port: int

    @property
    def production(self) -> bool:
        return self.environment == "production"

    def problems(self) -> list[str]:
        problems: list[str] = []
        if self.production:
            if not self.api_token:
                problems.append("REVENUE_RESCUE_API_TOKEN is required in production")
            if not self.cron_secret:
                problems.append("REVENUE_RESCUE_CRON_SECRET is required in production")
            if not self.database_url:
                problems.append("DATABASE_URL or SUPABASE_DB_URL is required in production")
        if not 1 <= self.port <= 65535:
            problems.append("PORT must be between 1 and 65535")
        return problems

    def public_status(self) -> dict:
        return {
            "environment": self.environment,
            "production": self.production,
            "api_auth_configured": bool(self.api_token),
            "cron_auth_configured": bool(self.cron_secret),
            "database_configured": bool(self.database_url),
            "scrapling_enabled": self.scrapling_enabled,
        }


def load_config() -> RuntimeConfig:
    environment = os.environ.get("REVENUE_RESCUE_ENV", "development").strip().lower()
    if environment not in {"development", "test", "staging", "production"}:
        environment = "development"

    database_url = (
        os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("SUPABASE_DB_URL", "").strip()
    )
    raw_port = os.environ.get("PORT", "8787").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = -1

    return RuntimeConfig(
        environment=environment,
        api_token=os.environ.get("REVENUE_RESCUE_API_TOKEN", "").strip(),
        cron_secret=os.environ.get("REVENUE_RESCUE_CRON_SECRET", "").strip(),
        database_url=database_url,
        scrapling_enabled=os.environ.get("REVENUE_RESCUE_SCRAPLING", "1") != "0",
        port=port,
    )


def assert_startup_ready(config: RuntimeConfig | None = None) -> RuntimeConfig:
    config = config or load_config()
    problems = config.problems()
    if problems:
        raise RuntimeError("invalid Revenue Rescue configuration: " + "; ".join(problems))
    return config
