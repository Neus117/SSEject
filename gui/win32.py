"""Win32 细节：DPI 感知、标题栏图标、深色标题栏。

Tk 在 Windows 上只有 ``iconbitmap`` 一个设图标的接口，而它**只从 ICO 里挑
一帧**再拉伸：175% 缩放下标题栏要 28×28、任务栏要 56×56，拿 16×16 拉伸
出来就是糊的。这里按窗口所在显示器的 DPI 用 ``LoadImageW`` 取真实尺寸的
帧，再 ``WM_SETICON``——顺带把"左上角还是默认羽毛"的问题一起解决。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Dict, Optional, Tuple

IS_WINDOWS = os.name == "nt"

# 进程级 DPI 感知
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1

SM_CXSMICON = 49
SM_CXICON = 11

GA_ROOT = 2

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19

_ICON_CACHE: Dict[Tuple[str, int, int], Tuple[int, int]] = {}


def enable_dpi_awareness() -> None:
    """必须在创建任何窗口之前调用，否则窗口按 96 DPI 排版再被系统拉伸。"""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        )
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # pragma: no cover
        pass


def root_hwnd(widget) -> int:
    """取真正的顶层窗口句柄（Tk 的 toplevel 外面还套了一层 wrapper）。"""
    try:
        handle = int(widget.winfo_id())
    except Exception:
        return 0
    if not handle or not IS_WINDOWS:
        return handle
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        root = user32.GetAncestor(wintypes.HWND(handle), GA_ROOT)
        return int(root or 0) or handle
    except Exception:  # pragma: no cover
        return handle


def window_dpi(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        dpi = int(user32.GetDpiForWindow(wintypes.HWND(hwnd)))
        return dpi or 96
    except Exception:
        return 96


def icon_metric(index: int, dpi: int) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        user32.GetSystemMetricsForDpi.restype = ctypes.c_int
        size = int(user32.GetSystemMetricsForDpi(index, dpi))
        if size > 0:
            return size
    except Exception:
        pass
    try:
        return int(ctypes.windll.user32.GetSystemMetrics(index)) or 16
    except Exception:  # pragma: no cover
        return 16


def _load_icon(path: str, size: int) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HICON
        LR_LOADFROMFILE = 0x0010
        IMAGE_ICON = 1
        handle = user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        return int(handle or 0)
    except Exception:  # pragma: no cover
        return 0


def set_window_icon(window, ico_path: Optional[str]) -> None:
    """按窗口 DPI 给标题栏与任务栏设置图标（失败静默）。"""
    if not IS_WINDOWS or not ico_path or not os.path.exists(ico_path):
        return
    try:
        window.update_idletasks()
    except Exception:
        pass
    hwnd = root_hwnd(window)
    if not hwnd:
        return
    dpi = window_dpi(hwnd)
    small_size = icon_metric(SM_CXSMICON, dpi)
    big_size = icon_metric(SM_CXICON, dpi)
    key = (ico_path, small_size, big_size)
    handles = _ICON_CACHE.get(key)
    if handles is None:
        handles = (_load_icon(ico_path, small_size), _load_icon(ico_path, big_size))
        _ICON_CACHE[key] = handles
    small, big = handles
    try:
        if small:
            ctypes.windll.user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_SMALL, small)
        if big:
            ctypes.windll.user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_BIG, big)
    except Exception:  # pragma: no cover
        pass


def window_icon_handles(window) -> Tuple[int, int]:
    """读回 ``WM_GETICON`` 的小/大图标句柄（0 表示没设上）。"""
    hwnd = root_hwnd(window)
    if not hwnd:
        return (0, 0)
    WM_GETICON = 0x007F
    try:
        user32 = ctypes.windll.user32
        small = int(user32.SendMessageW(wintypes.HWND(hwnd), WM_GETICON, ICON_SMALL, 0))
        big = int(user32.SendMessageW(wintypes.HWND(hwnd), WM_GETICON, ICON_BIG, 0))
        return (small, big)
    except Exception:  # pragma: no cover
        return (0, 0)


def load_icon_handle(path: str, size: int) -> int:
    """从 ICO 里按尺寸取一个句柄（诊断用；失败返回 0）。"""
    return _load_icon(path, size)


def set_dark_titlebar(window, dark: bool) -> None:
    """深色主题下把**非客户区**也变深（客户区自绘碰不到标题栏）。"""
    if not IS_WINDOWS:
        return
    hwnd = root_hwnd(window)
    if not hwnd:
        return
    try:
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY):
            if dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
    except Exception:  # pragma: no cover
        pass


def center_on(parent, window) -> None:
    """把 ``window`` 摆在 ``parent`` 的中心（先量尺寸，再定位）。

    窗口还没映射时 ``winfo_width`` 返回 1，必须退回 ``winfo_reqwidth``，
    否则算出来的位置会偏掉半个窗口。
    """
    try:
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        if width <= 1:
            width = window.winfo_reqwidth()
        if height <= 1:
            height = window.winfo_reqheight()
        px = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        px = max(0, min(px, screen_w - width))
        py = max(0, min(py, screen_h - height))
        window.geometry(f"+{px}+{py}")
    except Exception:  # pragma: no cover
        pass


def asset_path(*parts: str) -> Optional[str]:
    """找打包/开发两种形态下的资源文件（``assets/<parts>``）。"""
    candidates = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(os.path.join(base, "assets", *parts))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(here, "assets", *parts))
    candidates.append(os.path.join(os.getcwd(), "assets", *parts))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def python_icon_path() -> Optional[str]:
    """主图标（窗口/任务栏/EXE 资源）。"""
    return asset_path("app.ico")
