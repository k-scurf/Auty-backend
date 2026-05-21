"""Pipeline settings (merged from server settings dict)."""

from __future__ import annotations

from typing import Any, Dict

_CFG: Dict[str, Any] = {}


def configure(settings: dict) -> None:
    global _CFG
    _CFG = dict(settings)


def get_cfg(key: str, default=None):
    return _CFG.get(key, default)


def cfg() -> Dict[str, Any]:
    return _CFG
