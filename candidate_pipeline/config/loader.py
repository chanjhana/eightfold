"""Load + validate a projection config JSON into a ProjectionConfig (PRD §11).

A malformed config is a hard error before any profile is processed.
"""

from __future__ import annotations

import json
from pathlib import Path

import candidate_pipeline
from candidate_pipeline.config.schema import ProjectionConfig

_CONFIG_DIR = Path(candidate_pipeline.__file__).parent / "data" / "configs"


def load_config(path: str) -> ProjectionConfig:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return ProjectionConfig.model_validate(data)


def _load_default() -> ProjectionConfig:
    return load_config(str(_CONFIG_DIR / "default_config.json"))


DEFAULT_CONFIG = _load_default()
