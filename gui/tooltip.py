"""tkinter 的轻量提示条（悬停 400ms 显示）。

Tk 没有内置 tooltip，而"脱机→联机"这种按钮只看四个字看不出会做什么，
所以提示条是**功能的一部分**，不是装饰。
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class Tooltip:
    """给控件挂一条悬停提示；一个实例服务一个控件。"""

    def __init__(self, widget, text: str, *, palette, metrics, fonts, delay: int = 400):
        self.widget = widget
        self.text = text
        self.palette = palette
        self.metrics = metrics
        self.fonts = fonts
        self.delay = delay
        self._after_id: Optional[str] = None
        self._window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return          # 控件已被销毁（换主题/语言时），别用死句柄建窗口
        except tk.TclError:  # pragma: no cover
            return
        px = self.metrics.px
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_attributes("-topmost", True)
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background=self.palette.text,
            foreground=self.palette.surface,
            font=self.fonts.small,
            padx=px(8),
            pady=px(4),
        )
        label.pack()
        self.widget.update_idletasks()
        x = self.widget.winfo_rootx() + px(4)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(4)
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:  # pragma: no cover
                pass
            self._window = None
