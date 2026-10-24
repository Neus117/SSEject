"""设置面板：目前承载「主题」选择（跟随系统 / 浅色 / 深色）。

同一条规则：设置项都从这里进，主窗口不再单独放主题按钮。
窗口是自绘 Toplevel，配色跟随当前主题，深色下标题栏也变深。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from gui import theme, win32
from gui.tooltip import Tooltip

#: 逻辑宽度（高度按内容）
WINDOW_WIDTH = 360

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

        body = ttk.Frame(window, padding=(px(16), px(14), px(16), px(12)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="主题", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, px(16)))

        row = ttk.Frame(body)
        row.grid(row=0, column=1, sticky="w")
        self.buttons = {}
        for index, (value, icon, tip) in enumerate(_THEME_CHOICES):
            button = ttk.Button(
                row, image=self._icon(icon), style="Icon.TButton",
                command=lambda v=value: self._choose(v),
            )
            button.grid(row=0, column=index, padx=(0 if index == 0 else px(8), 0))
            self._tooltips.append(Tooltip(button, tip, palette=palette,
                                          metrics=metrics, fonts=fonts))
            self.buttons[value] = button

        footer = ttk.Frame(window)
        footer.pack(fill="x", padx=px(16), pady=(0, px(14)))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="关闭", style="Accent.TButton",
                   command=self.close).grid(row=0, column=1, sticky="e")

        win32.set_window_icon(window, icon_path)
        if palette.is_dark:
            win32.set_dark_titlebar(window, True)
        self._refresh_selection()

        window.update_idletasks()
        win32.center_on(parent, window)
        window.deiconify()
        window.grab_set()
        window.focus_force()
        window.after(60, lambda: self._reapply_chrome())
        self.parent.wait_window(window)

    # ------------------------------------------------------------------ 内部 --
    def _icon(self, name: str) -> tk.PhotoImage:
        size = self._icon_size()
        key = (name, size)
        image = self._images.get(key)
        if image is None:
            path = win32.asset_path(
                "icons", f"{name}-{size}-{self.palette.name}-normal.png")
            image = tk.PhotoImage(master=self.window, file=path)
            self._images[key] = image
        return image

    def _icon_size(self) -> int:
        target = self.metrics.px(16)
        return min((16, 20, 24, 28, 32, 36, 40, 48),
                   key=lambda value: (abs(value - target), value))

    def _refresh_selection(self) -> None:
        for value, button in self.buttons.items():
            style = "SelectedIcon.TButton" if value == self.mode else "Icon.TButton"
            button.configure(style=style)

    def _choose(self, value: str) -> None:
        if value == self.mode:
            return
        self.mode = value
        self._refresh_selection()
        # 主窗口要按新主题重建，这里先关掉，避免两边主题不一致
        self.close()
        self.on_theme(value)

    def _reapply_chrome(self) -> None:
        try:
            if not self.window.winfo_exists():
                return
            win32.set_window_icon(self.window, self.icon_path)
            if self.palette.is_dark:
                win32.set_dark_titlebar(self.window, True)
        except tk.TclError:  # pragma: no cover
            pass

    def close(self) -> None:
        try:
            self.window.grab_release()
        except tk.TclError:  # pragma: no cover
            pass
        self.window.destroy()
