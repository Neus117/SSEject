"""直接读写磁盘的脱机属性，以及强制卸载卷（方案 C）。

为什么不用 diskpart：在这台机器上 ``select disk`` + ``offline disk`` +
``online disk`` 三条命令本身要 3.6~6.5 秒，而
``IOCTL_DISK_SET_DISK_ATTRIBUTES`` 是毫秒级。diskpart 保留为兜底
（老系统 / 驱动不支持 / 打不开句柄时）。

结构体必须严格按 winioctl.h：

* ``GET_DISK_ATTRIBUTES {DWORD Version; DWORD Reserved1; ULONGLONG Attributes;}``
* ``SET_DISK_ATTRIBUTES {DWORD Version; BOOLEAN Persist; BYTE Reserved1[3];
  DWORD Attributes; DWORD AttributesMask; DWORD Reserved2[4];}``

之前把 SET 也当成 GET 的结构传（Version 用 ULONGLONG），驱动认为参数非法，
返回 ``ERROR_INVALID_FUNCTION(1)``——日志里"IOCTL 不可用（错误 1）"就是这个。

返回值约定：

* ``True``  —— 操作完成且读回状态正确；
* ``False`` —— 调用了但失败（例如磁盘不支持、被占用）；
* ``None``  —— 这个接口在本机不可用（打不开句柄 / 非 Windows）。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Optional

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3

IOCTL_DISK_GET_DISK_ATTRIBUTES = 0x000700F0
IOCTL_DISK_SET_DISK_ATTRIBUTES = 0x0007C0F4
DISK_ATTRIBUTE_OFFLINE = 0x0000000000000001

FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_UNLOCK_VOLUME = 0x0009001C


IS_WINDOWS = os.name == "nt"

_KERNEL32 = None
_LAST_ERROR = 0


def last_error() -> int:
    """最近一次失败的 Win32 错误码（0 表示没有记录）。"""
    return _LAST_ERROR


def _kernel32():
    global _KERNEL32
    if _KERNEL32 is None:
        _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _KERNEL32


def _create_file(path: str, access: int):
    global _LAST_ERROR
    kernel32 = _kernel32()
    create = kernel32.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(
        path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if not handle or int(handle) == int(ctypes.c_void_p(-1).value):
        _LAST_ERROR = ctypes.get_last_error()
        return None
    return handle


def _open(index: int, write: bool):
    """打开物理磁盘；失败返回 None（错误码记在 ``last_error()``）。"""
    if not IS_WINDOWS:
        return None
    access = GENERIC_READ | (GENERIC_WRITE if write else 0)
    return _create_file(rf"\\.\PhysicalDrive{int(index)}", access)


def _open_volume(letter: str):
    """打开 ``X:`` 卷句柄；失败返回 None。"""
    if not IS_WINDOWS:
        return None
    return _create_file(rf"\\.\{letter}:", GENERIC_READ | GENERIC_WRITE)


def _close(handle) -> None:
    try:
        _kernel32().CloseHandle(handle)
    except Exception:  # pragma: no cover
        pass


def _device_io_control(handle, code: int, in_buffer=None,
                       in_size: int = 0, out_buffer=None,
                       out_size: int = 0) -> bool:
    global _LAST_ERROR
    kernel32 = _kernel32()
    control = kernel32.DeviceIoControl
    control.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    control.restype = wintypes.BOOL
    returned = wintypes.DWORD(0)
    ok = bool(control(handle, code, in_buffer, in_size,
                      out_buffer, out_size, ctypes.byref(returned), None))
    if not ok:
        _LAST_ERROR = ctypes.get_last_error()
    return ok


class GET_DISK_ATTRIBUTES(ctypes.Structure):
    """winioctl.h：{DWORD Version; DWORD Reserved1; ULONGLONG Attributes;}"""
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("Reserved1", wintypes.DWORD),
        ("Attributes", ctypes.c_ulonglong),
    ]


class SET_DISK_ATTRIBUTES(ctypes.Structure):
    """winioctl.h：{DWORD Version; BOOLEAN Persist; BYTE Reserved1[3];
    DWORD Attributes; DWORD AttributesMask; DWORD Reserved2[4];}"""
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("Persist", wintypes.BOOLEAN),
        ("Reserved1", wintypes.BYTE * 3),
        ("Attributes", wintypes.DWORD),
        ("AttributesMask", wintypes.DWORD),
        ("Reserved2", wintypes.DWORD * 4),
    ]


def _read_attributes(handle) -> Optional[int]:
    attributes = GET_DISK_ATTRIBUTES()
    attributes.Version = ctypes.sizeof(GET_DISK_ATTRIBUTES)
    ok = _device_io_control(
        handle,
        IOCTL_DISK_GET_DISK_ATTRIBUTES,
        out_buffer=ctypes.byref(attributes),
        out_size=ctypes.sizeof(attributes),
    )
    return int(attributes.Attributes) if ok else None


#: SET 的 Version：MS 文档写 sizeof(GET_DISK_ATTRIBUTES)=16，实际驱动两种都见过；
#: 先按结构体自身大小（32），失败再试 16。
_SET_VERSIONS = (ctypes.sizeof(SET_DISK_ATTRIBUTES), ctypes.sizeof(GET_DISK_ATTRIBUTES))


def _write_offline(handle, offline: bool) -> bool:
    attributes = SET_DISK_ATTRIBUTES()
    attributes.Persist = True
    attributes.Attributes = DISK_ATTRIBUTE_OFFLINE if offline else 0
    attributes.AttributesMask = DISK_ATTRIBUTE_OFFLINE
    for version in _SET_VERSIONS:
        attributes.Version = version
        if _device_io_control(
            handle,
            IOCTL_DISK_SET_DISK_ATTRIBUTES,
            in_buffer=ctypes.byref(attributes),
            in_size=ctypes.sizeof(attributes),
        ):
            return True
    return False


def read_offline(index: int) -> Optional[bool]:
    """读磁盘是否脱机；读不到返回 None（不抛异常）。"""
    handle = _open(index, write=False)
    if handle is None:
        handle = _open(index, write=True)
    if handle is None:
        return None
    try:
        attributes = _read_attributes(handle)
        if attributes is None:
            return None
        return bool(attributes & DISK_ATTRIBUTE_OFFLINE)
    finally:
        _close(handle)


def set_offline(index: int, offline: bool) -> Optional[bool]:
    """置/清脱机属性，并读回确认。语义见模块文档。"""
    handle = _open(index, write=True)
    if handle is None:
        return None
    try:
        attributes = _read_attributes(handle)
        if attributes is None:
            return False
        if bool(attributes & DISK_ATTRIBUTE_OFFLINE) == offline:
            return True
        if not _write_offline(handle, offline):
            return False
        after = _read_attributes(handle)
        if after is None:
            return False
        return bool(after & DISK_ATTRIBUTE_OFFLINE) == offline
    finally:
        _close(handle)


def volume_lockable(letter: str) -> Optional[bool]:
    """卷能不能被排他锁定：True=没有打开句柄，False=有句柄在用，None=查不了。

    这是判断"弹出被拒是因为有程序占着文件，还是仅仅卷还挂着"的最便宜探针。
    """
    handle = _open_volume(letter)
    if handle is None:
        return None
    try:
        ok = _device_io_control(handle, FSCTL_LOCK_VOLUME)
        if ok:
            _device_io_control(handle, FSCTL_UNLOCK_VOLUME)
        return ok
    finally:
        _close(handle)
