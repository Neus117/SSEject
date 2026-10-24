"""测量打包后的 EXE「从双击到窗口出现」的耗时（开发/验收工具）。

为什么要单独写：PyInstaller 单文件模式的 **父进程只是引导器**，
真正的窗口属于它启动的子进程。``Start-Process`` 拿到的是父进程，
``MainWindowHandle`` 永远是 0——按父进程判断"窗口出来了没有"一定会
误判为 30 秒没出来。这里直接枚举窗口标题。

用法::

    python tools/probe_startup.py dist/QuickPortableDiskTool.exe --runs 3
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Optional

user32 = ctypes.windll.user32


def find_window(title_part: str) -> int:
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_part in buffer.value and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(_callback, 0)
    return found[0] if found else 0


def wait_window(title_part: str, timeout: float) -> Optional[float]:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if find_window(title_part):
            return time.perf_counter() - started
        time.sleep(0.02)
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("exe")
    parser.add_argument("--title", default="可移动磁盘快速脱机")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    results = []
    for run in range(1, args.runs + 1):
        process = subprocess.Popen([args.exe, "--no-elevate"])
        elapsed = wait_window(args.title, args.timeout)
        results.append(elapsed)
        print(f"run {run}: {elapsed:.2f}s" if elapsed else f"run {run}: 窗口未出现")
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )
        time.sleep(1.0)
    good = [value for value in results if value]
    if good:
        print(f"min={min(good):.2f}s max={max(good):.2f}s avg={sum(good)/len(good):.2f}s")
    return 0 if len(good) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
