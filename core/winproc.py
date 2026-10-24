"""隐藏控制台窗口的子进程调用（唯一入口）。

原来的实现把这个函数复制了三份（``disk_query`` / ``eject`` / ``diskpart_ops``），
三份之间已经开始分叉——例如 ``eject`` 那份漏了 ``wShowWindow = SW_HIDE``，
于是弹出流程偶尔会闪一个黑框。这里收敛成一份。

设计要点：

* **可执行文件用绝对路径**（``%SystemRoot%\\System32\\...``）。按名字调用
  ``powershell`` / ``diskpart`` 会走 ``PATH``，而 ``PATH`` 里当前目录优先，
  在别人的目录里启动时就等于执行那个目录里的同名程序。
* **每个调用都有硬超时**；超时后杀**进程树**（``taskkill /F /T``），
  不是只杀直接子进程——``powershell`` 会再起 ``WmiPrvSE`` 之类的子进程。
* **编码按调用方声明**：PowerShell 输出由脚本自己转成 UTF-8；
  ``diskpart`` 输出是控制台 OEM 代码页（中文系统为 cp936）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .i18n import L

SYSTEM_ROOT = os.environ.get("SystemRoot", r"C:\Windows")
SYSTEM32 = os.path.join(SYSTEM_ROOT, "System32")
POWERSHELL = os.path.join(
    SYSTEM32, "WindowsPowerShell", "v1.0", "powershell.exe"
)
DISKPART = os.path.join(SYSTEM32, "diskpart.exe")

CREATE_NO_WINDOW = 0x08000000
SW_HIDE = 0
STARTF_USESHOWWINDOW = 0x00000001

#: PowerShell 公共前缀：错误即抛出、输出改 UTF-8（否则中文机型按 cp936 输出，
#: Python 侧再用 UTF-8 解码就会把磁盘型号变成乱码）。
PS_PREFIX = (
    "$ErrorActionPreference='Stop';"
    "try{[Console]::OutputEncoding=[Text.Encoding]::UTF8}catch{};"
)

#: ``-Command`` 参数：不再让 PowerShell 自己去解析文件，也不加载用户配置。
PS_ARGS = [
    POWERSHELL,
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
]


class CommandError(RuntimeError):
    """子进程返回非零退出码。"""

    def __init__(self, message: str, output: str = "", returncode: int = -1):
        super().__init__(message)
        self.output = output
        self.returncode = returncode


class CommandTimeout(CommandError):
    """子进程在限定时间内没有结束（已强制结束进程树）。"""


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _popen_kwargs() -> Dict[str, object]:
    kwargs: Dict[str, object] = {}
    if os.name != "nt":
        return kwargs
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE
    kwargs["startupinfo"] = startupinfo
    kwargs["creationflags"] = CREATE_NO_WINDOW
    return kwargs


def kill_tree(pid: int) -> None:
    """强制结束进程树；失败不抛异常（清理路径不该再引入新错误）。"""
    if os.name != "nt" or not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=10,
            **_popen_kwargs(),
        )
    except Exception:  # pragma: no cover - 清理失败不影响主流程
        pass


def run(
    cmd: Sequence[str],
    *,
    input_text: Optional[str] = None,
    timeout: float = 20.0,
    encoding: str = "utf-8",
    env: Optional[Dict[str, str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> CommandResult:
    """运行命令并返回解码后的输出；超时抛 :class:`CommandTimeout`。"""
    run_env = None
    if env is not None:
        run_env = dict(env)
    elif extra_env:
        run_env = dict(os.environ)
    if run_env is not None and extra_env:
        run_env.update(extra_env)

    proc = subprocess.Popen(
        list(cmd),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=run_env,
        **_popen_kwargs(),
    )
    payload = input_text.encode(encoding, errors="replace") if input_text is not None else None
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        try:
            proc.communicate(timeout=5)
        except Exception:  # pragma: no cover
            pass
        raise CommandTimeout(
            L(f"命令执行超时（{timeout:.0f} 秒）：{os.path.basename(cmd[0])}",
              f"Command timed out after {timeout:.0f}s: {os.path.basename(cmd[0])}"),
            returncode=-1,
        )
    return CommandResult(
        returncode=proc.returncode,
        stdout=(out or b"").decode(encoding, errors="replace"),
        stderr=(err or b"").decode(encoding, errors="replace"),
    )


def run_powershell(
    script: str,
    *,
    timeout: float = 20.0,
    extra_env: Optional[Dict[str, str]] = None,
) -> CommandResult:
    """执行一段 PowerShell 脚本；失败时抛 :class:`CommandError`。"""
    result = run(
        PS_ARGS + [PS_PREFIX + script],
        timeout=timeout,
        encoding="utf-8",
        extra_env=extra_env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CommandError(
            detail or L(f"PowerShell 退出码 {result.returncode}",
                        f"PowerShell exit code {result.returncode}"),
            output=result.output,
            returncode=result.returncode,
        )
    return result


def run_diskpart(lines: List[str], *, timeout: float = 30.0) -> CommandResult:
    """把一组 diskpart 命令喂给同一个 diskpart 进程。

    注意：``diskpart`` **即使命令失败也返回退出码 0**，成败必须由
    :mod:`core.diskpart_ops` 按最终状态判断。
    """
    script = "\r\n".join(lines) + "\r\n"
    try:
        return run(
            [DISKPART],
            input_text=script,
            timeout=timeout,
            encoding="mbcs",
        )
    except OSError as exc:
        # 非管理员时 Popen 会直接抛 WinError 740（要求提升）
        raise CommandError(L(f"无法启动 diskpart：{exc.strerror or exc}",
                                     f"Cannot start diskpart: {exc.strerror or exc}")) from exc
