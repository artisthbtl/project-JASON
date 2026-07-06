from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env(*, override: bool = True) -> bool:
    """Load environment variables from the project-level .env file."""
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "python-dotenv is required to load the project .env file. "
            "Install it with: pip install python-dotenv"
        ) from exc

    return bool(load_dotenv(dotenv_path=ENV_PATH, override=override))


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {value!r}.") from exc
