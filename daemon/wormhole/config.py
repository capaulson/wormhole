"""Configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class DaemonConfig(BaseModel):
    port: int = 7117
    buffer_size: int = 1000


class DiscoveryConfig(BaseModel):
    enabled: bool = True
    service_name: str = "wormhole"


class DefaultsConfig(BaseModel):
    model: str = "claude-sonnet-4-5"
    permission_mode: str = "default"


class Config(BaseModel):
    daemon: DaemonConfig = DaemonConfig()
    discovery: DiscoveryConfig = DiscoveryConfig()
    defaults: DefaultsConfig = DefaultsConfig()


def load_config() -> Config:
    """Load configuration from file and environment."""
    config_path = Path.home() / ".config" / "wormhole" / "config.toml"

    config_dict: dict[str, Any] = {}

    if config_path.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)

    # Environment overrides
    if port := os.environ.get("WORMHOLE_PORT"):
        config_dict.setdefault("daemon", {})["port"] = int(port)
    if buffer_size := os.environ.get("WORMHOLE_BUFFER_SIZE"):
        config_dict.setdefault("daemon", {})["buffer_size"] = int(buffer_size)

    return Config.model_validate(config_dict)
