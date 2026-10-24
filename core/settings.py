"""用户设置（主题 / 语言）的持久化。

路径：``%LOCALAPPDATA%\\SSEject\\settings.json``。读不到或内容损坏时退回默认值，
不抛异常——设置坏了不该让程序起不来。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from . import i18n

APP_DIR_NAME = "SSEject"

#: 默认值：主题跟随系统；语言留空表示"按系统语言挑"
DEFAULTS: Dict[str, Any] = {"theme": "system", "language": ""}

_VALID_THEMES = ("system", "light", "dark")


def settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / APP_DIR_NAME / "settings.json"


def load() -> Dict[str, Any]:
    values = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return values
    if isinstance(stored, dict):
        for key in DEFAULTS:
            if key in stored and isinstance(stored[key], str):
                values[key] = stored[key]
    if values["theme"] not in _VALID_THEMES:
        values["theme"] = DEFAULTS["theme"]
    if values["language"] not in i18n.CHOICES:
        values["language"] = DEFAULTS["language"]
    return values


def save(values: Dict[str, Any]) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(values, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError:
        pass


def update(**changes: Any) -> Dict[str, Any]:
    """读—改—写：返回合并后的完整设置。"""
    values = load()
    values.update(changes)
    if values["theme"] not in _VALID_THEMES:
        values["theme"] = DEFAULTS["theme"]
    if values["language"] not in i18n.CHOICES:
        values["language"] = DEFAULTS["language"]
    save(values)
    return values
