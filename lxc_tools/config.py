"""Configuration loading for lxc-tools.

Configuration values are resolved with the following precedence (highest first):

1. Environment variables (``LXC_ZFS_POOL``, ``LXC_PRIV_PATH``,
   ``LXC_UNPRIV_BASE``, ``BASE_PROJECT_DIR``, ``LXC_NET_LINK``)
2. ``/etc/lxc-tools/lxc-tools.conf``
3. ``~/.config/lxc-tools/lxc-tools.conf``
4. ``./lxc-tools.conf`` (current working directory)
5. Safe built-in defaults (``rpool``, ``lxcbr0``, ``/opt/project``)
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

# Config files in ascending precedence order (later files override earlier ones).
CONFIG_PATHS = (
    Path("/etc/lxc-tools/lxc-tools.conf"),
    Path.home() / ".config" / "lxc-tools" / "lxc-tools.conf",
    Path("lxc-tools.conf"),
)

# Environment variable -> Config field name.
ENV_MAP = {
    "LXC_ZFS_POOL": "zfs_pool",
    "LXC_PRIV_PATH": "priv_path",
    "LXC_UNPRIV_BASE": "unpriv_base",
    "BASE_PROJECT_DIR": "project_dir",
    "LXC_NET_LINK": "bridge",
}

# INI key -> Config field name. INI sections are ignored; keys are matched by
# lowercase name across all sections (e.g. [zfs] pool=rpool).
INI_MAP = {
    "pool": "zfs_pool",
    "priv_path": "priv_path",
    "unpriv_base": "unpriv_base",
    "project_dir": "project_dir",
    "bridge": "bridge",
}


class ConfigError(Exception):
    """Raised when the configuration cannot be loaded."""


@dataclass(frozen=True)
class Config:
    """Resolved lxc-tools configuration.

    ``priv_path`` and ``unpriv_base`` default to paths derived from
    ``zfs_pool`` unless explicitly configured.
    """

    zfs_pool: str = "rpool"
    priv_path: str = "/rpool/lxc/privileged"
    unpriv_base: str = "/rpool/lxc/unprivileged"
    project_dir: str = "/opt/project"
    bridge: str = "lxcbr0"

    def __post_init__(self) -> None:
        for field in ("zfs_pool", "priv_path", "unpriv_base", "project_dir", "bridge"):
            if not getattr(self, field):
                raise ConfigError(f"Configuration value '{field}' must not be empty.")


def _read_ini_values() -> dict[str, str]:
    """Flatten all config files into a ``{lowercase_key: value}`` mapping."""
    values: dict[str, str] = {}
    parser = configparser.ConfigParser(interpolation=None)
    for path in CONFIG_PATHS:
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                parser.read_file(handle)
        except (configparser.Error, OSError) as exc:
            raise ConfigError(f"Could not parse config file {path}: {exc}") from exc
        for section in parser.sections():
            for key, value in parser.items(section):
                values[key.lower()] = value
    return values


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    """Load configuration following the documented precedence order."""
    environ = os.environ if environ is None else environ
    cfg = Config()
    explicit: set[str] = set()

    ini_values = _read_ini_values()
    for key, attr in INI_MAP.items():
        if key in ini_values:
            cfg = replace(cfg, **{attr: ini_values[key]})
            explicit.add(attr)

    for env_var, attr in ENV_MAP.items():
        value = environ.get(env_var)
        if value:
            cfg = replace(cfg, **{attr: value})
            explicit.add(attr)

    # Apply pool-derived defaults only for paths that were not explicitly set.
    cfg = replace(
        cfg,
        priv_path=cfg.priv_path
        if "priv_path" in explicit
        else f"/{cfg.zfs_pool}/lxc/privileged",
        unpriv_base=cfg.unpriv_base
        if "unpriv_base" in explicit
        else f"/{cfg.zfs_pool}/lxc/unprivileged",
    )
    return cfg
