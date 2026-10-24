"""用 Windows 自己的"安全移除"接口请求弹出设备。

为什么不用 ``pnputil /remove-device``：那是**强制删除设备节点**。卷还挂载时
Windows 会返回 3010（重启后生效），磁盘对象没了、卷却留在系统里，盘符甚至
再也回不来。``CM_Request_Device_Eject`` 是资源管理器"安全删除硬件"用的同一个
接口：先让驱动卸载卷、再移除设备；有程序占用时返回 **veto 原因**，而不是硬删。

注意：磁盘节点本身通常不可弹出，会返回 ``PNP_VetoIllegalDeviceRequest``。
真正该弹的是它上面的可移动设备节点（USB 设备），所以这里沿父节点往上找
第一个带 EJECTSUPPORTED / REMOVABLE 能力的节点再请求。

返回 ``(成功?, 说明)``；失败时的说明可以直接写进日志给用户看。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Optional, Tuple

from .i18n import L

IS_WINDOWS = os.name == "nt"

CR_SUCCESS = 0
CR_NO_SUCH_DEVNODE = 0x0D
CR_INVALID_DEVNODE = 0x1B
CR_ACCESS_DENIED = 0x33

CM_DRP_CAPABILITIES = 0x00000010
CM_DEVCAP_EJECTSUPPORTED = 0x00000002
CM_DEVCAP_REMOVABLE = 0x00000004
EVICTABLE_CAPABILITIES = CM_DEVCAP_EJECTSUPPORTED | CM_DEVCAP_REMOVABLE

#: PNP_VETO_TYPE → （中文, English）。存成二元组而不是成品字符串：
#: 成品字符串会在 import 时把语言“冻住”，用户之后在设置里换语言就不生效了。
VETO_TEXT = {
    0: ("未知原因", "Unknown reason"),
    1: ("旧式设备无法安全移除", "Legacy device cannot be removed safely"),
    2: ("设备正在关闭，稍后重试", "Device is shutting down, try again later"),
    3: ("有应用程序正在使用该设备", "An application is using the device"),
    4: ("有系统服务正在使用该设备", "A system service is using the device"),
    5: ("仍有文件或句柄处于打开状态", "Files or handles are still open"),
    6: ("设备本身拒绝移除", "The device itself refused removal"),
    7: ("驱动拒绝移除", "The driver refused removal"),
    8: ("非法的移除请求", "Invalid removal request"),
    9: ("电源不足", "Insufficient power"),
    10: ("设备不允许禁用", "The device cannot be disabled"),
    11: ("旧式驱动拒绝移除", "A legacy driver refused removal"),
    12: ("权限不足（需要管理员）", "Access denied (administrator required)"),
}

#: `CM_Request_Device_EjectW` 的 veto 码：8 = 非法请求（这一层节点不可弹出，继续往上找）
_VETO_INVALID_REQUEST = 8


def veto_text(code: int) -> str:
    """把 veto 码翻成当前语言的说明。"""
    pair = VETO_TEXT.get(int(code))
    if pair is None:
        return L(f"未知原因（{code}）", f"Unknown reason ({code})")
    return L(*pair)


def _cfgmgr():
    return ctypes.WinDLL("cfgmgr32")


def _bind(cfgmgr) -> None:
    cfgmgr.CM_Locate_DevNodeW.argtypes = [
        ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR, wintypes.DWORD
    ]
    cfgmgr.CM_Locate_DevNodeW.restype = wintypes.ULONG
    cfgmgr.CM_Get_Parent.argtypes = [
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.DWORD
    ]
    cfgmgr.CM_Get_Parent.restype = wintypes.ULONG
    cfgmgr.CM_Get_Device_IDW.argtypes = [
        wintypes.DWORD, wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG
    ]
    cfgmgr.CM_Get_Device_IDW.restype = wintypes.ULONG
    cfgmgr.CM_Get_DevNode_Registry_PropertyW.argtypes = [
        wintypes.DWORD, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
        wintypes.LPVOID, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG,
    ]
    cfgmgr.CM_Get_DevNode_Registry_PropertyW.restype = wintypes.ULONG
    cfgmgr.CM_Request_Device_EjectW.argtypes = [
        wintypes.DWORD, ctypes.POINTER(ctypes.c_int), wintypes.LPWSTR,
        wintypes.ULONG, wintypes.ULONG,
    ]
    cfgmgr.CM_Request_Device_EjectW.restype = wintypes.ULONG


def _device_id(cfgmgr, node: int) -> str:
    buffer = ctypes.create_unicode_buffer(260)
    code = int(cfgmgr.CM_Get_Device_IDW(node, buffer, 260, 0))
    return buffer.value if code == CR_SUCCESS else ""


def _parent_of(cfgmgr, node: int) -> Optional[int]:
    parent = wintypes.DWORD(0)
    code = int(cfgmgr.CM_Get_Parent(ctypes.byref(parent), node, 0))
    return int(parent.value) if code == CR_SUCCESS else None


def _capabilities(cfgmgr, node: int) -> int:
    """读 devnode 的 CM_DRP_CAPABILITIES；读不到返回 0。"""
    value = wintypes.DWORD(0)
    size = wintypes.ULONG(ctypes.sizeof(value))
    kind = wintypes.ULONG(0)
    code = int(cfgmgr.CM_Get_DevNode_Registry_PropertyW(
        node, CM_DRP_CAPABILITIES, ctypes.byref(kind),
        ctypes.byref(value), ctypes.byref(size), 0))
    return int(value.value) if code == CR_SUCCESS else 0


def _eject_node(cfgmgr, node: int) -> Tuple[bool, str, int]:
    """请求弹出一个节点；返回 (是否成功, 原因文案, veto 码)。"""
    veto = ctypes.c_int(0)
    name = ctypes.create_unicode_buffer(260)
    code = int(cfgmgr.CM_Request_Device_EjectW(
        node, ctypes.byref(veto), name, 260, 0))
    if code == CR_SUCCESS:
        return True, "", 0
    veto_code = int(veto.value)
    reason = veto_text(veto_code)
    who = (name.value or "").strip()
    if code == CR_ACCESS_DENIED:
        reason = L("权限不足（需要管理员）", "Access denied (administrator required)")
    separator = L("：", ": ")
    return False, reason + (separator + who if who else ""), veto_code


def candidate_nodes(cfgmgr, node: int) -> list:
    """从磁盘节点往上，列出带"可弹出"能力的节点（调试用）。"""
    found = []
    for _ in range(6):
        if _capabilities(cfgmgr, node) & EVICTABLE_CAPABILITIES:
            found.append((node, _device_id(cfgmgr, node)))
        parent = _parent_of(cfgmgr, node)
        if parent is None or parent == node:
            break
        node = parent
    return found


def request_eject(instance_id: str) -> Tuple[bool, str]:
    """请求 PnP 管理器安全移除 ``instance_id`` 对应的设备（自动上溯到可弹节点）。"""
    if not IS_WINDOWS or not instance_id:
        return False, L("非 Windows 或设备 ID 为空", "Not Windows, or the device ID is empty")
    try:
        cfgmgr = _cfgmgr()
        _bind(cfgmgr)
    except Exception as exc:  # pragma: no cover - 极老系统
        return False, L(f"系统不支持该接口：{exc}", f"This interface is not supported: {exc}")

    devinst = wintypes.DWORD(0)
    code = int(cfgmgr.CM_Locate_DevNodeW(ctypes.byref(devinst), instance_id, 0))
    if code != CR_SUCCESS:
        if code == CR_NO_SUCH_DEVNODE:
            return True, L("设备节点已不存在（视为已移除）", "Device node is gone (treated as removed)")
        return False, L(f"找不到设备节点（CONFIGRET {code}）", f"Device node not found (CONFIGRET {code})")

    node = int(devinst.value)
    last_reason = ""
    for _ in range(6):
        if _capabilities(cfgmgr, node) & EVICTABLE_CAPABILITIES:
            ok, reason, veto_code = _eject_node(cfgmgr, node)
            if ok:
                return True, ""
            last_reason = reason
            # 磁盘节点自己不可弹出：继续往上找可移动设备节点。
            # 判据用 veto 码，不能拿本地化后的文案去匹配（换语言就失效）
            if veto_code != _VETO_INVALID_REQUEST:
                return False, reason
        parent = _parent_of(cfgmgr, node)
        if parent is None or parent == node:
            break
        node = parent
    return False, last_reason or L("没有找到可安全移除的设备节点",
                                   "No safely removable device node found")
