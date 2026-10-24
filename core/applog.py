"""应用日志文件（``%LOCALAPPDATA%\\SSEject\\app.log``）。

调试日志不能写在程序目录：PyInstaller 单文件模式下那是**临时解压目录**，
程序一退出就消失，打包后也可能不可写。这里统一放到用户目录，并在 1 MB 时轮转。

文件以 UTF-8 **带 BOM** 写入：PowerShell 5.1 的 ``Get-Content`` 默认按 ANSI 解码，
没有 BOM 时中文日志会变成乱码。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "SSEject"
MAX_BYTES = 1024 * 1024
_BOM = b"\xef\xbb\xbf"
_LOCK = threading.Lock()
_PATH: Optional[Path] = None
_BOM_READY = False


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / APP_DIR_NAME


def log_path() -> Path:
    global _PATH
    if _PATH is None:
        _PATH = log_dir() / "app.log"
    return _PATH


def _ensure_bom(path: Path) -> None:
    """让日志文件以 UTF-8 BOM 开头。

    没有 BOM 时，Windows PowerShell 5.1 的 ``Get-Content`` 按系统 ANSI
    （中文机器是 GBK）解码，中文全变成乱码。带 BOM 后 5.1 / 7 都能正确识别；
    已存在的旧日志一次性补上 BOM（内容本身是 UTF-8）。
    """
    global _BOM_READY
    if _BOM_READY:
        return
    _BOM_READY = True
    try:
        if path.exists() and path.stat().st_size:
            data = path.read_bytes()
            if not data.startswith(_BOM):
                path.write_bytes(_BOM + data)
        else:
            path.write_bytes(_BOM)
    except OSError:
        pass


def _rotate(path: Path) -> None:
    global _BOM_READY
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            backup = path.with_suffix(".log.1")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
            _BOM_READY = False
    except OSError:
        pass


def write(level: str, message: str) -> None:
    """写一条日志；任何 I/O 失败都静默（日志不能反过来弄坏界面）。"""
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{level.upper():5s}] {message}"
    with _LOCK:
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate(path)
            _ensure_bom(path)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            return


def tail(limit: int = 200) -> str:
    """读回最后若干行（帮助窗里的"打开日志"失败时兜底显示用）。"""
    try:
        with open(log_path(), "r", encoding="utf-8-sig", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    return "".join(lines[-limit:])


def open_in_explorer() -> bool:
    """在资源管理器里选中日志文件；返回是否成功。"""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        return True
    except OSError:
        return False
