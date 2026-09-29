"""Environment-driven configuration. Keys are read from the environment only, never hardcoded."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class MissingConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(f"{name} is not set. See .env.example.")
    return value


@dataclass(frozen=True)
class Settings:
    nebius_api_key: str
    nebius_ai_project: str | None
    tavily_api_key: str | None
    db_path: str
    spend_cap_usd: float


def load_settings(*, need_tavily: bool = False, need_project: bool = False) -> Settings:
    return Settings(
        nebius_api_key=_require("NEBIUS_API_KEY"),
        nebius_ai_project=_require("NEBIUS_AI_PROJECT") if need_project
        else os.environ.get("NEBIUS_AI_PROJECT"),
        tavily_api_key=_require("TAVILY_API_KEY") if need_tavily
        else os.environ.get("TAVILY_API_KEY"),
        db_path=os.environ.get("PALISSY_DB_PATH", "data/palissy.db"),
        spend_cap_usd=float(os.environ.get("PALISSY_SPEND_CAP_USD", "5.00")),
    )
