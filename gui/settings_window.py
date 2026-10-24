"""设置面板：两个平级的类——「主题」（跟随系统 / 浅色 / 深色）与「语言」（CN / EN）。

排版原则（与经验库一致）：

* 分区块：标题在上、控件在下；同一个类里控件间距 n，类与类之间 2n；
* 窗口宽度固定、高度随内容，四周留白 24 / 20；
* 「关闭」单独成行，和设置区之间留 20 逻辑像素，不贴着作用控件。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from core import i18n
from core.i18n import L
from gui import win32
from gui.iconbutton import IconButton
from gui.tooltip import Tooltip

#: 逻辑尺寸与间距（全部是 4 的倍数；`GROUP_GAP` = 4n，也是「关闭」的左间距）
#: 窗口宽 432：4n 间距下「主题 + 语言 + 关闭」需要 384 逻辑宽（152 + 40 + 98 + 40 + 54），
#: 420 减去左右各 24 只剩 372，差 12 —— 要么窗口宽 12、要么左右边距缩到 16。
#: 取前者：关闭按钮的位置不动、左右边距仍然都是 24。
WINDOW_WIDTH = 432
PAD_X = 24
PAD_TOP = 20
PAD_BOTTOM = 18
LABEL_GAP = 12      #: 区块标题与控件行之间
FOOTER_GAP = 20     #: 设置区与「关闭」之间
ICON_GAP = 10       #: n：同一个类里控件之间的间距
GROUP_GAP = 4 * ICON_GAP   #: 类与类之间 = 4n（「关闭」与语言类之间也用这个值）

_THEME_CHOICES = (
    ("system", "monitor", ("跟随系统", "Follow system")),
    ("light", "sun", ("浅色", "Light")),
    ("dark", "moon", ("深色", "Dark")),
)

#: 语言类：图标位置直接写字（正文字体 + 加粗），不绘图
_LANGUAGE_CHOICES = (("zh", "CN"), ("en", "EN"))


class SettingsWindow:
    """模态设置窗；改主题/语言会立刻回调主窗口重建界面。"""

    def __init__(self, parent: tk.Misc, *, palette, metrics, fonts,
                 icon_path: Optional[str], theme_mode: str, language: str,
                 on_theme: Callable[[str], None],
                 on_language: Callable[[str], None]):
        self.parent = parent
        self.palette = palette
        self.metrics = metrics
        self.fonts = fonts
        self.icon_path = icon_path
        self.on_theme = on_theme
        self.on_language = on_language
        self.mode = theme_mode
        self.language = language
        self._images = {}
        self._tooltips = []

        px = metrics.px
        window = tk.Toplevel(parent)
        self.window = window
        window.withdraw()
        window.title(L("设置", "Settings"))
        window.transient(parent)
        window.resizable(False, False)
        window.configure(background=palette.background)

        body = ttk.Frame(window, padding=(px(PAD_X), px(PAD_TOP), px(PAD_X), px(PAD_BOTTOM)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # 主题类、语言类、关闭放进同一个网格：
        #   col0 = 主题类，col1 = 语言类（左间距 4n），col2 = 关闭（左间距 4n）
        # grid 的列从上一格的右边缘量起，所以「关闭」的左边缘恰好是
        # 「语言」类右边缘 + 4n —— 两个横向间距因此必然相等。
        layout = ttk.Frame(body)
        layout.grid(row=0, column=0, sticky="w")

        side = px(44)
        # ---- 主题类 ------------------------------------------------------
        theme_block = ttk.Frame(layout)
        theme_block.grid(row=0, column=0, sticky="w")
        ttk.Label(theme_block, text=L("主题", "Theme"),
                  style="Section.TLabel").grid(row=0, column=0, sticky="w")
        theme_row = ttk.Frame(theme_block)
        theme_row.grid(row=1, column=0, sticky="w", pady=(px(LABEL_GAP), 0))

        self.buttons = {}
        for index, (value, icon, tip) in enumerate(_THEME_CHOICES):
            size = self._icon_size()
            button = IconButton(
                theme_row, palette=palette, metrics=metrics,
                icon_paths={
                    "normal": self._icon_path(icon, size, "normal"),
                    "hover": self._icon_path(icon, size, "hover"),
                },
                command=lambda v=value: self._choose(v),
                width=side, height=side, fonts=fonts,
                selected=(value == self.mode),
            )
            button.grid(row=0, column=index, padx=(0 if index == 0 else px(ICON_GAP), 0))
            self._tooltips.append(Tooltip(button, L(*tip), palette=palette,
                                          metrics=metrics, fonts=fonts))
            self.buttons[value] = button

        # ---- 语言类（在主题右边，类与类之间 4n）---------------------------
        current = i18n.resolve(self.language)
        lang_block = ttk.Frame(layout)
        lang_block.grid(row=0, column=1, sticky="w", padx=(px(GROUP_GAP), 0))
        ttk.Label(lang_block, text=L("语言", "Language"),
                  style="Section.TLabel").grid(row=0, column=0, sticky="w")
        lang_row = ttk.Frame(lang_block)
        lang_row.grid(row=1, column=0, sticky="w", pady=(px(LABEL_GAP), 0))

        self.lang_buttons = {}
        for index, (value, label) in enumerate(_LANGUAGE_CHOICES):
            button = IconButton(
                lang_row, palette=palette, metrics=metrics, icon_paths={},
                command=lambda v=value: self._choose_language(v),
                width=side, height=side, fonts=fonts,
                text=label, font=fonts.lang_text,
                selected=(value == current),
            )
            button.grid(row=0, column=index, padx=(0 if index == 0 else px(ICON_GAP), 0))
            self.lang_buttons[value] = button

        # ---- 关闭（横向间距与类之间一致：语言类右边缘 + 4n）----------------
        ttk.Button(layout, text=L("关闭", "Close"), style="Accent.TButton",
                   command=self.close).grid(
            row=1, column=2, sticky="w",
            padx=(px(GROUP_GAP), 0), pady=(px(FOOTER_GAP), 0))

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

    def _refresh_language(self) -> None:
        current = i18n.resolve(self.language)
        for value, button in self.lang_buttons.items():
            button.set_selected(value == current)

    def _choose(self, value: str) -> None:
        if value == self.mode:
            return
        self.mode = value
        self._refresh_selection()
        # 主窗口要按新主题重建，这里先关掉，避免两边主题不一致
        self.close()
        self.on_theme(value)

    def _choose_language(self, value: str) -> None:
        if value == i18n.resolve(self.language):
            return
        self.language = value
        self._refresh_language()
        # 与主题一致：主窗口要按新语言重建，先关掉本窗口
        self.close()
        self.on_language(value)

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
