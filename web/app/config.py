"""Configuration serveur (variables d'environnement, voir docker-compose.yml)."""
from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ot:ot@db:5432/ot"
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
