"""Load API credentials separately from serializable experiment configuration."""
from __future__ import annotations

import os
from pathlib import Path


def load_api_key(config):
    env_name = config.get("api_key_env", "AGI_RESEARCH_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    filename = config.get("api_key_file")
    if filename:
        path = Path(filename).expanduser()
        if path.is_file():
            key = path.read_text().strip()
            if key:
                return key
    if config.get("requires_api_key", False):
        raise RuntimeError(f"API credential missing: set {env_name} or configure api_key_file")
    return None
