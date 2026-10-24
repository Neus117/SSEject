"""Canvas 版图标按钮：热追踪覆盖**整个按钮**，而不是图标周围的一小块。

为什么不用 ttk.Button + 图片：

* PNG 里烤进去的底色只有图标那么大，按钮比图标宽——悬停换图时只有中间那块
  变色，看起来就是"热追踪只在一个小方框里生效"；
* 想靠 ttk 自己变色，就必须让图片透明；Tk 对半透明边缘的处理不可靠。

所以这里用 Canvas 当按钮面：底色由 Canvas 自己画，悬停时**整块**换成
``surface_hover``（深色下是 ``#363636``），图标图里烤的底色与 Canvas 一致，
换色时同时换图，不会露方块；高度直接由调用方给（与文字按钮一致）。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from gui.tooltip import Tooltip


class IconButton(tk.Canvas):
    """一个方形/长方形图标按钮：整块热追踪 + 点击 + 禁用态。"""

    def __init__(self, master, *, palette, metrics, icon_paths: dict,
                 command: Callable[[], None], width: int, height: int,
                 tooltip: Optional[str] = None, fonts=None, selected: bool = False):
        super().__init__(master, width=width, height=height,
                         background=palette.surface, highlightthickness=0, bd=0,
                         takefocus=True)
        self.palette = palette
        self.command = command
        self.paths = icon_paths          # {"normal": path, "hover": path}
        self.selected = selected
        self.enabled = True
        self._hover = False
        self._images = {}
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Key-space>", self._on_click)
        self.bind("<Key-Return>", self._on_click)
        self._paint()
        self.tooltip = None
        if tooltip:
            self.tooltip = Tooltip(self, tooltip, palette=palette,
                                   metrics=metrics, fonts=fonts)

    # ------------------------------------------------------------------ 内部 --
    def _image(self, state: str) -> Optional[tk.PhotoImage]:
        path = self.paths.get(state)
        if not path:
            return None
        image = self._images.get(state)
        if image is None:
            image = tk.PhotoImage(master=self, file=path)
            self._images[state] = image
        return image

    def _paint(self) -> None:
        self.delete("all")
        surface = self.palette.surface_hover if self._hover else self.palette.surface
        self.configure(background=surface)
        self.create_rectangle(0, 0, int(self["width"]), int(self["height"]),
                              fill=surface, outline="")
        if self.selected:
            self.create_rectangle(1, 1, int(self["width"]) - 1, int(self["height"]) - 1,
                                  outline=self.palette.accent, width=2)
        image = self._image("hover" if self._hover else "normal")
        if image is not None:
            self.create_image(int(self["width"]) // 2, int(self["height"]) // 2,
                              image=image)

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        if self.enabled:
            self.configure(cursor="hand2")
        self._paint()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self.configure(cursor="")
        self._paint()

    def _on_click(self, _event=None) -> None:
        if self.enabled and self.command is not None:
            self.command()

    # ------------------------------------------------------------------ API --
    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._paint()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._paint()
