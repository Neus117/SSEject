"""diskpart 脱机 / 联机。

原实现只看退出码，而 **diskpart 即使命令失败也返回 0**：非管理员、盘号不存在、
该磁盘不支持脱机——三种情况都会在输出里报错、退出码仍是 0，界面于是显示
"执行成功"。这里改成**以最终状态为准**：

1. 跑完 diskpart 后用 ``Get-Disk`` 读 ``IsOffline``（与界面"状态"列同一个数据源）；
2. 状态查询不可用（极老系统 / 非管理员）时，才退回解析中/英成败标记；
3. ``脱机→联机`` 合成**一个** diskpart 进程（原来是两个，约 4 秒），
   并允许"本来就是脱机"导致的离线报错——只要最终是联机就算成功。
"""

from __future__ import annotations

from typing import List, Optional

from . import applog, disk_attr, winproc

#: 命中任意一条即判失败（中文 / 英文版 Windows）
_FAILURE_MARKERS = (
    "错误",
    "失败",
    "拒绝访问",
    "无效",
    "不存在",
    "找不到",
    "不受支持",
    "error",
    "failed",
    "access is denied",
    "invalid",
    "not found",
    "is not supported",
    "no disk",
    "does not exist",
)

#: 已知的成功标记（只在状态未知时用于日志判断）
_SUCCESS_MARKERS = ("成功", "successfully", "success")


class DiskpartError(RuntimeError):
    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output


def _first_failure_line(output: str) -> str:
    for line in output.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in _FAILURE_MARKERS):
            return line.strip()
    return ""


def _run_raw(lines: List[str], *, timeout: float = 30.0) -> str:
    try:
        result = winproc.run_diskpart(lines, timeout=timeout)
    except winproc.CommandError as exc:
        raise DiskpartError(str(exc)) from exc
    return (result.stdout + result.stderr).strip()


def _check_index(index: int) -> int:
    try:
        number = int(index)
    except (TypeError, ValueError) as exc:
        raise DiskpartError(f"磁盘号无效：{index!r}") from exc
    if number < 0:
        raise DiskpartError(f"磁盘号无效：{number}")
    return number


def disk_is_offline(index: int) -> Optional[bool]:
    """读磁盘的脱机状态。优先 IOCTL（毫秒级），拿不到再退回 ``Get-Disk``。"""
    state = disk_attr.read_offline(int(index))
    if state is not None:
        return state
    script = (
        f"$d=Get-Disk -Number {int(index)} -ErrorAction Stop;"
        "if($d.IsOffline){'OFFLINE'}else{'ONLINE'}"
    )
    try:
        result = winproc.run_powershell(script, timeout=15)
    except winproc.CommandError:
        return None
    text = result.stdout or ""
    if "OFFLINE" in text:
        return True
    if "ONLINE" in text:
        return False
    return None


def _judge(action: str, output: str, state: Optional[bool], want_offline: bool) -> str:
    """状态优先；状态未知时退回文案标记。"""
    if state is not None:
        if state == want_offline:
            return output
        actual = "脱机" if state else "联机"
        wanted = "脱机" if want_offline else "联机"
        raise DiskpartError(f"{action}失败：磁盘仍处于{actual}状态（目标：{wanted}）", output)
    failure = _first_failure_line(output)
    if failure:
        raise DiskpartError(f"{action}失败：{failure}", output)
    return output


def _cim_set_offline(number: int, offline: bool) -> Optional[bool]:
    """用 Storage 模块（``Set-Disk``）置状态；返回最终是否脱机，失败返回 None。

    IOCTL 在这块 USB-SATA 桥上被拒（Win32 24 = ERROR_BAD_LENGTH），
    diskpart 又要 4 秒；Storage 模块走 WMI，实测一个进程约 0.5 秒。
    """
    flag = "$true" if offline else "$false"
    script = (
        f"$d=Get-Disk -Number {number} -ErrorAction Stop;"
        f"Set-Disk -InputObject $d -IsOffline {flag};"
        f"if((Get-Disk -Number {number}).IsOffline){{'OFFLINE'}}else{{'ONLINE'}}"
    )
    try:
        result = winproc.run_powershell(script, timeout=25)
    except winproc.CommandError as exc:
        applog.write("info", f"Storage 模块脱机/联机失败：{exc}")
        return None
    text = result.stdout or ""
    if "OFFLINE" in text:
        return True
    if "ONLINE" in text:
        return False
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    applog.write("info", "Storage 模块无有效输出："
                 + (detail[-1][:160] if detail else "（空）"))
    return None


def offline_disk(index: int) -> str:
    """把磁盘置为脱机（释放异常占用）。

    实测顺序（2026-10-24）：
    * IOCTL：这块 USB-SATA 桥一律返回错误 24 → 直接跳过；
    * Storage 模块（Set-Disk）：脱机约 1.3 s；
    * diskpart：约 2.1 s。
    所以先试 Storage 模块，失败再 diskpart。
    """
    number = _check_index(index)
    state = disk_attr.set_offline(number, True)
    if state is True:
        return f"已通过系统接口把磁盘 {number} 置为脱机（未调用 diskpart）。"
    applog.write("info", f"IOCTL 脱机失败（Win32 错误 {disk_attr.last_error()}），改用 Storage 模块")
    if _cim_set_offline(number, True) is True:
        return f"已通过 Storage 模块把磁盘 {number} 置为脱机。"
    applog.write("info", "Storage 模块脱机失败，改用 diskpart")
    output = _run_raw([f"select disk {number}", "offline disk"])
    return _judge(f"磁盘 {number} 脱机", output, disk_is_offline(number), True)


def online_disk(index: int) -> str:
    """把磁盘置回联机；顺序同 ``offline_disk``（Storage 模块约 0.2 s）。"""
    number = _check_index(index)
    state = disk_attr.set_offline(number, False)
    if state is True:
        return f"已通过系统接口把磁盘 {number} 置为联机（未调用 diskpart）。"
    applog.write("info", f"IOCTL 联机失败（Win32 错误 {disk_attr.last_error()}），改用 Storage 模块")
    if _cim_set_offline(number, False) is False:
        return f"已通过 Storage 模块把磁盘 {number} 置为联机。"
    applog.write("info", "Storage 模块联机失败，改用 diskpart")
    output = _run_raw([f"select disk {number}", "online disk"])
    return _judge(f"磁盘 {number} 联机", output, disk_is_offline(number), False)


