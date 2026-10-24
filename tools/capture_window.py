"""按窗口标题截图（开发/验收工具，不参与打包）。

用法::

    python tools/capture_window.py --title "可移动磁盘" --out shot.png

为什么不用 ``PIL.ImageGrab``：它抓的是**屏幕**，窗口一旦被别的窗口挡住或
被移到屏幕外，抓到的就是别人的画面。这里走 ``PrintWindow`` +
``PW_RENDERFULLCONTENT``，让窗口自己把客户区渲染到内存 DC，因此可以在
屏幕外抓图——测试窗口不必出现在用户桌面上。

失败时（全同色 / 全黑）退回 ``BitBlt`` 抓屏幕对应区域。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from typing import List, Optional, Tuple

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WM_SETICON = 0x0080

# 句柄必须显式声明成 64 位：不声明时 ctypes 按 C int 取返回值，DC/位图句柄会被
# 截断成 32 位（实测得到负数），随后传给 PrintWindow 直接 TypeError，或者更糟——
# 悄悄操作到别的 DC 上。
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.PrintWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                            wintypes.UINT]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_void_p


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def find_windows(title_part: str, pid: int = 0) -> List[Tuple[int, str]]:
    """按标题子串找可见窗口；给了 ``pid`` 就只认这个进程的窗口。

    只按标题匹配会抓到浏览器（页面标题里可能含同样的词），所以验收时用 ``--pid``。
    """
    found: List[Tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if pid:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if title_part in buf.value and user32.IsWindowVisible(hwnd):
            found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _grab(hwnd: int, rect: RECT, foreground: bool = False) -> Tuple[Image.Image, str]:
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"窗口尺寸异常: {width}x{height}")

    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    try:
        source = "printwindow"
        ok = user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, 2)  # PW_RENDERFULLCONTENT
        img = _to_image(mem_dc, bitmap, width, height)
        # PrintWindow 失败时拿到的是纯色（常见全黑/全白）画面，这时才退回抓屏幕。
        # 判"空白"只能用"整个画面只有一种颜色"：早先写成
        # ``getcolors(maxcolors=64)`` 并把 ``None`` 当全同色——而颜色数超过 64 时
        # getcolors 恰好返回 None，于是**任何彩色窗口都被判失败**、改抓屏幕；
        # 窗口一旦不在屏幕上或被挡住，抓到的就是别人的画面（实测：窗口在屏幕外时
        # 拿到一片纯白，却报告 source=printwindow 之外的东西）。
        if not ok or _is_blank(img):
            source = "bitblt"
        if source == "bitblt":
            if foreground:
                user32.SetForegroundWindow(wintypes.HWND(hwnd))
                user32.BringWindowToTop(wintypes.HWND(hwnd))
                time.sleep(0.35)
            gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc,
                         rect.left, rect.top, 0x00CC0020)
            img = _to_image(mem_dc, bitmap, width, height)
        return img, source
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


def _is_blank(img: Image.Image) -> bool:
    """整个画面只有一种颜色（PrintWindow 拿不到内容时的典型结果）。"""
    return all(low == high for low, high in img.getextrema())


def _to_image(dc: int, bitmap: int, width: int, height: int) -> Image.Image:
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0  # BI_RGB
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(dc, bitmap, 0, height, buf, ctypes.byref(info), 0)
    return Image.frombuffer("RGBA", (width, height), buf.raw,
                            "raw", "BGRA", 0, 1).convert("RGB")


def make_topmost(hwnd: int, topmost: bool = True) -> None:
    """临时置顶，绕开"前台锁"——被抓的窗口可能根本抢不到焦点。

    只用于抓图；抓完调用 :func:`make_topmost` 传 ``False`` 复位。
    """
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOPMOST if topmost else HWND_NOTOPMOST),
        0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )
    time.sleep(0.2)


def window_icon(hwnd: int) -> Tuple[int, int]:
    """读回 WM_GETICON 的小/大图标句柄（0 表示未设置）。"""
    return (int(user32.SendMessageW(hwnd, 0x007F, 0, 0)),
            int(user32.SendMessageW(hwnd, 0x007F, 1, 0)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="窗口标题子串")
    parser.add_argument("--pid", type=int, default=0, help="只认这个进程的窗口")
    parser.add_argument("--out", required=True, help="输出 PNG 路径")
    parser.add_argument("--report", action="store_true", help="打印窗口与图标句柄")
    parser.add_argument("--foreground", action="store_true",
                        help="抓屏幕前先把窗口提到前台（窗口被挡住时用）")
    parser.add_argument("--topmost", action="store_true",
                        help="抓之前临时置顶（窗口抢不到前台时用）")
    args = parser.parse_args(argv)

    enable_dpi_awareness()
    windows = find_windows(args.title, args.pid)
    if not windows:
        print("未找到窗口", file=sys.stderr)
        return 2
    hwnd, title = windows[0]
    if args.topmost:
        make_topmost(hwnd, True)
    rect = RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    img, source = _grab(hwnd, rect, args.foreground)
    img.save(args.out)
    if args.topmost:
        make_topmost(hwnd, False)
    print(f"hwnd={hwnd} size={img.size} source={source} out={args.out}")
    if args.report:
        print(f"icons(small,big)={window_icon(hwnd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
