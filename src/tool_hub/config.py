"""Configuration. `TH_`-prefixed environment variables or a `.env` file.

No list-typed fields: Pydantic Settings parses those as JSON, so `TH_X=a,b` fails with a decode
error that reads like a bug in the tool rather than a mistake in the value.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TH_", env_file=".env", extra="ignore")

    tools: Path = Path("data/tools")
    usage_log: Path = Path("data/usage.json")

    #: Climb to IMPORTABLE_HERE when checking requirements. Off by default because reaching
    #: that rung RUNS other people's module bodies, and a listing command should not.
    deep: bool = False
