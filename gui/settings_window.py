"""设置面板：目前承载「主题」选择（跟随系统 / 浅色 / 深色）。

排版原则（与经验库一致）：

* 分区块：标题在上、控件在下，块与块之间留整行空白；
* 窗口宽度固定、高度随内容，四周留白 24 / 20；
* 「关闭」单独成行，和设置区之间留 20 逻辑像素，不贴着作用控件。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from gui import win32
from gui.iconbutton import IconButton
from gui.tooltip import Tooltip

#: 逻辑尺寸与间距（全部是 4 的倍数）
WINDOW_WIDTH = 420
PAD_X = 24
PAD_TOP = 20
PAD_BOTTOM = 18
LABEL_GAP = 12      #: 区块标题与控件行之间
FOOTER_GAP = 20     #: 设置区与「关闭」之间

_THEME_CHOICES = (
    ("system", "monitor", "跟随系统"),
    ("light", "sun", "浅色"),
    ("dark", "moon", "深色"),
)


class SettingsWindow:
    """模态设置窗；改主题会立刻回调主窗口重建界面。"""

    def __init__(self, parent: tk.Misc, *, palette, metrics, fonts,
                 icon_path: Optional[str], theme_mode: str,
                 on_theme: Callable[[str], None]):
        self.parent = parent
        self.palette = palette
        self.metrics = metrics
        self.fonts = fonts
        self.icon_path = icon_path
        self.on_theme = on_theme
        self.mode = theme_mode
        self._images = {}
        self._tooltips = []

        px = metrics.px
        window = tk.Toplevel(parent)
        self.window = window
        window.withdraw()
        window.title("设置")
        window.transient(parent)
        window.resizable(False, False)
        window.configure(background=palette.background)

        body = ttk.Frame(window, padding=(px(PAD_X), px(PAD_TOP), px(PAD_X), px(PAD_BOTTOM)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # ---- 主题区块 ----------------------------------------------------
        ttk.Label(body, text="主题", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        row = ttk.Frame(body)
        row.grid(row=1, column=0, sticky="w", pady=(px(LABEL_GAP), 0))

        self.buttons = {}
        side = px(44)
        for index, (value, icon, tip) in enumerate(_THEME_CHOICES):
            size = self._icon_size()
            button = IconButton(
                row, palette=palette, metrics=metrics,
                icon_paths={
                    "normal": self._icon_path(icon, size, "normal"),
                    "hover": self._icon_path(icon, size, "hover"),
                },
                command=lambda v=value: self._choose(v),
                width=side, height=side, fonts=fonts,
                selected=(value == self.mode),
            )
            button.grid(row=0, column=index, padx=(0 if index == 0 else px(10), 0))
            self._tooltips.append(Tooltip(button, tip, palette=palette,
                                          metrics=metrics, fonts=fonts))
            self.buttons[value] = button

        # ---- 关闭 --------------------------------------------------------
        footer = ttk.Frame(body)
        footer.grid(row=2, column=0, sticky="ew", pady=(px(FOOTER_GAP), 0))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="关闭", style="Accent.TButton",
                   command=self.close).grid(row=0, column=1, sticky="e")

        win32.set_window_icon(window, icon_path)
        win32.set_dark_titlebar(window, palette.is_dark)
        self._refresh_selection()

        window.update_idletasks()
        self._place_centered()
        window.deiconify()
        window.grab_set()
        window.focus_force()
        window.after(60, self._reapply_chrome)
        self.parent.wait_window(window)

    # ------------------------------------------------------------------ 内部 --
    def _icon_path(self, name: str, size: int, state: str):
        return win32.asset_path(
            "icons", f"{name}-{size}-{self.palette.name}-{state}.png")

    def _icon_size(self) -> int:
        target = self.metrics.px(20)
        return min((20, 25, 30, 35, 40, 45, 50, 60),
                   key=lambda value: (abs(value - target), value))

    def _refresh_selection(self) -> None:
        for value, button in self.buttons.items():
            button.set_selected(value == self.mode)

    def _choose(self, value: str) -> None:
        if value == self.mode:
            return
        self.mode = value
        self._refresh_selection()
        # 主窗口要按新主题重建，这里先关掉，避免两边主题不一致
        self.close()
        self.on_theme(value)

    def _place_centered(self) -> None:
        px = self.metrics.px
        window = self.window
        width = px(WINDOW_WIDTH)
        height = window.winfo_reqheight()
        window.geometry(f"{width}x{height}")
        window.update_idletasks()
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2
        window.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def _reapply_chrome(self) -> None:
        try:
            if not self.window.winfo_exists():
                return
            win32.set_window_icon(self.window, self.icon_path)
            win32.set_dark_titlebar(self.window, self.palette.is_dark)
        except tk.TclError:  # pragma: no cover
            pass

    def close(self) -> None:
        try:
            self.window.grab_release()
        except tk.TclError:  # pragma: no cover
            pass
        self.window.destroy()
