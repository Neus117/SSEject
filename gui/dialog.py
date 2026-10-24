"""应用内模态对话框（替代 ``tkinter.messagebox``）。

为什么不用系统 MessageBox：

1. 它由系统绘制，客户区会被拆成「正文区 / 按钮区」两块底色——就是用户说的
   "三段式三明治"，我们改不了；本实现让**整个客户区只有一种底色**
   （标题栏由系统画，那是第二种，也是仅有的两种）；
2. 它只跟随系统主题，不跟随应用主题——深色应用里会弹出一个浅色框。

所以这里用 Toplevel 自绘：图标用 Canvas 画（几何图元，不是字体字形），
按钮复用 ttk 主题，深色下同时把标题栏设为深色。
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from core.i18n import L
from gui import win32

#: 正文的换行宽度（逻辑像素）
WRAP_WIDTH = 360
#: 图标画布边长（逻辑像素）
BADGE_SIZE = 43

#: 不能出现在行首的字符（避免"、"或"。"被甩到下一行开头）
_NO_LINE_START = "，。、；：？！）】》”’%·…"


def wrap_text(text: str, font, max_px: int) -> str:
    """按像素宽度手动折行。

    为什么不用 ``wraplength``：Tk 只在空格处断词，中文句子没有空格时
    会把整句当成一个词——第一行只放得下开头几个字，后面几行却塞满，
    看上去参差不齐。这里按字符贪心折行，并把标点留在上一行。
    """
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            if not current or font.measure(current + char) <= max_px:
                current += char
                continue
            if char in _NO_LINE_START:
                lines.append(current + char)
                current = ""
            else:
                lines.append(current)
                current = char
        lines.append(current)
    return "\n".join(lines)


#: 最近一次创建的对话框工厂。异常兜底（app.py 的 excepthook）拿不到主窗口
#: 引用，靠它把"程序出错"也画成同一套样式；没有就退回系统 MessageBox。
_ACTIVE: Optional["Dialogs"] = None


def active_dialogs() -> Optional["Dialogs"]:
    return _ACTIVE


#: 预渲染图标的像素边长（逻辑 36 × 常见 DPI 缩放）
_BADGE_SIZES = (43, 54, 65, 75, 86, 97, 108, 129)
_IMAGE_CACHE = {}


def _warning_geometry(s: float) -> dict:
    """警告三角的几何（与 ``tools/design_badges.py`` 的 ``warning_geometry`` 同一套）。

    等边三角形：底边 = ``s - 2*margin``、高 = 底 × √3/2，整枚三角形上移让**包围盒**
    在画布里垂直居中（用户要求等边；原来底 0.85、高 0.85 是等腰，两腰比底长）。
    两处必须一致——`tests/test_core.py` 里有一条用例逐点比对，改一边不改另一边会红。
    """
    margin = 0.075 * s
    base = s - 2.0 * margin
    height = base * math.sqrt(3.0) / 2.0
    bottom = s - margin
    top = bottom - height
    shift = (top + bottom) / 2.0 - s / 2.0
    top -= shift
    bottom -= shift
    stroke = 0.062 * s
    cx = s / 2.0
    apex = (cx, top)
    left = (margin, bottom)
    right = (s - margin, bottom)
    centroid_y = (apex[1] + left[1] + right[1]) / 3.0
    scale = max(0.55, 1.0 - (2.4 * stroke) / max(1.0, s - 2.0 * margin))
    inner = [(cx + (x - cx) * scale, centroid_y + (y - centroid_y) * scale)
             for x, y in (apex, left, right)]
    return {"apex": apex, "left": left, "right": right, "inner": inner,
            "centroid_y": centroid_y, "stroke": stroke}


def _draw_badge(canvas: tk.Canvas, kind: str, size: int, ink: str = "#000000") -> None:
    """兜底图标（资源缺失时才用）：三角/圆 + 两条矩形。

    Tk 的 Canvas 没有抗锯齿，这条路径的斜边会有锯齿——正常路径是
    ``assets/badges/*.png``（Pillow 16 倍渲染 + 平均降采样）。几何与 PNG
    保持一致（见 :func:`_warning_geometry`）：等边线框三角、感叹号按重心垂直居中。
    """
    canvas.delete("all")
    s = size
    if kind in ("warning", "question"):
        background = canvas.cget("background") or "#F3F4F6"
        geometry = _warning_geometry(float(s))
        apex = geometry["apex"]
        left = geometry["left"]
        right = geometry["right"]
        inner = geometry["inner"]
        centre = geometry["centroid_y"]
        stroke = geometry["stroke"]
        cx = apex[0]
        canvas.create_polygon(*[v for p in (apex, left, right) for v in p],
                              fill=ink, outline="")
        canvas.create_polygon(*[v for p in inner for v in p],
                              fill=background, outline="")
        length = s * 0.20
        gap = s * 0.060
        dot_radius = s * 0.050
        total = length + gap + 2.0 * dot_radius
        top = centre - total / 2.0
        bottom = top + length
        dot_y = bottom + gap + dot_radius
        half = stroke / 2.0
        canvas.create_rectangle(cx - half, top, cx + half, bottom,
                                fill=ink, outline="")
        for cap_y in (top, bottom):
            canvas.create_oval(cx - half, cap_y - half, cx + half, cap_y + half,
                               fill=ink, outline="")
        canvas.create_oval(cx - dot_radius, dot_y - dot_radius,
                           cx + dot_radius, dot_y + dot_radius,
                           fill=ink, outline="")
        return
    fill = "#C42B1C" if kind == "error" else "#0067C0"
    canvas.create_oval(s * 0.04, s * 0.04, s * 0.96, s * 0.96, fill=fill, outline="")
    mark = "#FFFFFF"
    centre = s * 0.5
    width, bar, gap, dot = s * 0.080, s * 0.330, s * 0.070, s * 0.080
    top = centre - (bar + gap + dot) / 2.0
    x0, x1 = s * 0.5 - width / 2.0, s * 0.5 + width / 2.0
    canvas.create_rectangle(x0, top, x1, top + bar, fill=mark, outline="")
    canvas.create_rectangle(x0, top + bar + gap, x1, top + bar + gap + dot,
                            fill=mark, outline="")


class Dialogs:
    """一个窗口的对话框工厂；所有调用都在主线程上（模态嵌套事件循环）。"""

    def __init__(self, parent: tk.Misc, *, palette, metrics, fonts,
                 icon_path: Optional[str]):
        global _ACTIVE
        self.parent = parent
        self.palette = palette
        self.metrics = metrics
        self.fonts = fonts
        self.icon_path = icon_path
        _ACTIVE = self

    # ------------------------------------------------------------------ API --
    def info(self, title: str, message: str) -> None:
        self._run(title, message, kind="info", buttons=[(L("确定", "OK"), True, True)], default=0)

    def warning(self, title: str, message: str) -> None:
        self._run(title, message, kind="warning", buttons=[(L("确定", "OK"), True, False)], default=0)

    def error(self, title: str, message: str) -> None:
        self._run(title, message, kind="error", buttons=[(L("确定", "OK"), True, False)], default=0)

    def confirm(self, title: str, message: str, *, default_yes: bool = False) -> bool:
        """是 / 否。``default_yes=False`` 时"否"是默认动作，也是强调色所在。"""
        buttons = [(L("是", "Yes"), True, default_yes), (L("否", "No"), False, not default_yes)]
        return bool(self._run(title, message, kind="question", buttons=buttons,
                              default=0 if default_yes else 1))

    # -------------------------------------------------------------- 实现 --
    def _run(self, title: str, message: str, *, kind: str,
             buttons: List[tuple], default: int) -> bool:
        px = self.metrics.px
        palette = self.palette
        result = {"value": False}

        window = tk.Toplevel(self.parent)
        window.withdraw()
        window.title(title)
        window.transient(self.parent)
        window.resizable(False, False)
        window.configure(background=palette.background)

        body = ttk.Frame(window, padding=(px(20), px(16), px(20), px(14)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        image = self._badge_image(kind)
        badge_px = image.width() if image is not None else px(BADGE_SIZE)
        badge = tk.Canvas(body, width=badge_px, height=badge_px,
                          background=palette.background, highlightthickness=0,
                          bd=0)
        badge.grid(row=0, column=0, sticky="n", padx=(0, px(12)))
        if image is not None:
            badge.create_image(badge_px // 2, badge_px // 2, image=image)
            badge.image = image  # 防止被 GC 回收
        else:
            _draw_badge(badge, kind, badge_px, palette.text)

        text = ttk.Label(body, text=wrap_text(message, self.fonts.body, px(WRAP_WIDTH)),
                         justify="left", background=palette.background,
                         foreground=palette.text, font=self.fonts.body)
        text.grid(row=0, column=1, sticky="w")

        row = ttk.Frame(body)
        row.grid(row=1, column=0, columnspan=2, sticky="e", pady=(px(16), 0))

        # 对话框按钮比工具条按钮宽一档：单字按钮（是/否）按自然宽度只有 47 逻辑像素，
        # 比 Windows 的对话框按钮窄太多。
        button_padding = (px(28), px(6))
        handlers = []
        for position, (label, value, accent) in enumerate(buttons):
            button = ttk.Button(
                row, text=label,
                style="Accent.TButton" if accent else "TButton",
                padding=button_padding,
                command=lambda v=value: self._finish(window, result, v),
            )
            button.grid(row=0, column=position, padx=(px(8) if position else 0, 0))
            handlers.append(button)

        default_button = handlers[default]
        window.bind("<Return>", lambda _event: default_button.invoke())
        window.bind("<Escape>", lambda _event: self._finish(window, result, buttons[-1][1]))

        win32.set_window_icon(window, self.icon_path)
        win32.set_dark_titlebar(window, palette.is_dark)

        self._place_centered(window)
        window.deiconify()
        window.grab_set()
        window.focus_force()
        default_button.focus_set()
        window.after(60, lambda: self._reapply_chrome(window, default_button))

        self.parent.wait_window(window)
        return result["value"]

    def _badge_image(self, kind: str) -> Optional[tk.PhotoImage]:
        """挑一张与目标像素尺寸最接近的预渲染图标（不缩放，保持清晰）。

        PNG 是**不透明**的：底色已经烤进像素。Tk 对"既有 alpha=0 又有半透明"
        的图会丢掉部分透明，锯齿会回来（实测）。
        ``question`` 没有单独的图：确认框和警告框用同一枚线框三角。
        """
        target = self.metrics.px(BADGE_SIZE)
        size = min(_BADGE_SIZES, key=lambda value: (abs(value - target), value))
        key = (kind, size, self.palette.name)
        if key in _IMAGE_CACHE:
            return _IMAGE_CACHE[key]
        image = None
        asset_kind = "warning" if kind == "question" else kind
        path = win32.asset_path("badges", f"{asset_kind}-{size}-{self.palette.name}.png")
        if path:
            try:
                image = tk.PhotoImage(master=self.parent, file=path)
            except tk.TclError:  # pragma: no cover - 资源损坏
                image = None
        _IMAGE_CACHE[key] = image
        return image

    def _place_centered(self, window: tk.Toplevel) -> None:
        px = self.metrics.px
        window.update_idletasks()
        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        x = self.parent.winfo_rootx() + (self.parent.winfo_width() - width) // 2
        y = self.parent.winfo_rooty() + (self.parent.winfo_height() - height) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _reapply_chrome(self, window: tk.Toplevel, default_button: ttk.Button) -> None:
        # 映射之后再设一次：未映射时 DWM 属性可能不生效（见 gui/win32.py）
        try:
            if not window.winfo_exists():
                return
            win32.set_window_icon(window, self.icon_path)
            win32.set_dark_titlebar(window, self.palette.is_dark)
            default_button.focus_set()
        except tk.TclError:  # pragma: no cover
            pass

    @staticmethod
    def _finish(window: tk.Toplevel, result: dict, value) -> None:
        result["value"] = value
        try:
            window.grab_release()
        except tk.TclError:  # pragma: no cover
            pass
        window.destroy()
