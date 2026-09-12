"""Configuration utilisateur simple (stockée en JSON local, ex : clé API Gemini)."""
from __future__ import annotations

import json

from app.paths import data_dir

CONFIG_FILE = "config.json"


def _config_path():
    return data_dir() / CONFIG_FILE


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    _config_path().write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def get_gemini_api_key() -> str | None:
    key = load_config().get("gemini_api_key")
    return key.strip() if key and key.strip() else None


def set_gemini_api_key(key: str | None) -> None:
    config = load_config()
    if key and key.strip():
        config["gemini_api_key"] = key.strip()
    else:
        config.pop("gemini_api_key", None)
    save_config(config)
