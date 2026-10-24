"""UAC 提权：判断当前进程权限，必要时以管理员身份重启自身。

设计取舍：提权被用户取消时**不退出**——主界面以只读模式继续运行，并在状态栏
和日志里说明"只能查看、不能执行磁盘操作"。这样"双击没反应"不会发生。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from typing import List, Optional

#: 命令行开关
SKIP_FLAG = "--no-elevate"      #: 显式跳过提权（测试/CI 用）
DONE_FLAG = "--elevated"        #: 已提权过的标记，避免反复弹 UAC

#: ShellExecuteW 返回值 > 32 才算成功发起
_SHELL_EXEC_OK = 32


def has_admin_rights() -> bool:
    """当前进程是否具备管理员权限。"""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 极老系统
        return False


def spawn_elevated(extra_args: Optional[List[str]] = None) -> bool:
    """以 ``runas`` 方式重启自身；返回是否成功**发起**（UAC 被拒时返回 False）。"""
    if sys.platform != "win32":
        return False
    raw = sys.argv[1:] if extra_args is None else list(extra_args)
    args = [arg for arg in raw if arg != SKIP_FLAG]
    if DONE_FLAG not in args:
        args.append(DONE_FLAG)
    command_line = subprocess.list2cmdline(args)
    try:
        code = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", sys.executable, command_line, None, 0
        )
    except Exception:  # pragma: no cover
        return False
    return int(code) > _SHELL_EXEC_OK


def decide_admin_state(argv: Optional[List[str]] = None) -> str:
    """返回 ``admin`` / ``relaunched`` / ``denied`` / ``skipped``。

    * ``admin``：已经是管理员；
    * ``relaunched``：已发起提权重启，**调用方必须立即退出**；
    * ``denied``：提权被拒（或以管理员身份重启后仍不是管理员）；
    * ``skipped``：命令行显式跳过提权。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if has_admin_rights():
        return "admin"
    if SKIP_FLAG in args:
        return "skipped"
    if DONE_FLAG in args:
        return "denied"
    return "relaunched" if spawn_elevated(args) else "denied"
