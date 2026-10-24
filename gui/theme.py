"""配色、字体、ttk 样式与 DPI（界面数值的唯一来源）。

数值纪律（来自视觉规范）：

* 间距全部是 **4 的倍数**，逻辑像素，经 :meth:`Metrics.px` 换算一次；
* 字号：正文 / 按钮 **10pt**，次要信息 **9pt**（= 系统 UI 一档）；
* 圆角与控件高度由 ttk 主题决定，不在业务代码里写死；
* 字体全局只有一套（Microsoft YaHei UI 回退链），不逐控件指定。

颜色取用户定稿的调色板（与 GUI-of-Edge-TTS 的 LIGHT / DARK 同源）；
深色主题按注册表的 ``AppsUseLightTheme`` 自动跟随系统。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk
from typing import Optional

try:  # pragma: no cover - 非 Windows 走默认浅色
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# 间距网格（4 的倍数，逻辑像素）
# --------------------------------------------------------------------------- #
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_6 = 24

#: 磁盘表/日志的最小行高（逻辑像素），用于分隔条的最小尺寸
ROW_HEIGHT = 26
LOG_LINE_HEIGHT = 18

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 430
WINDOW_MIN_WIDTH = 620
WINDOW_MIN_HEIGHT = 380

FONT_BODY_PT = 10
FONT_SMALL_PT = 9

#: 单字符图标（帮助的“?”）字号与字重。要的是“比 normal 粗、比 bold 细”的中间态：
#: 微软雅黑只有 normal/bold 两档，所以这一枚改用真正带 Semibold 档的家族（单个 ASCII
#: 字形，不涉及中文回退）。Semibold 的字面比同 pt 的雅黑小一档，所以字号按实测往上
#: 提到 +7.5pt（168 DPI 下 41px），墨迹高度才与原来 15.5pt 的雅黑（36px）一致。
#:
#: tkinter 的 size 只能是整数，写小数会抛 ``TclError: expected integer``（日志实证），
#: 所以按当前 DPI 换成整数**像素**字号——Tk 内部本来也是这么把 point 换成像素的。
GLYPH_PT = FONT_BODY_PT + 7.5
GLYPH_FAMILY = "Segoe UI Semibold"

#: “?”的画法微调：墨迹中心比行框中心**低**约 5% 字号，画的时候往上挪回来
GLYPH_NUDGE_RATIO = 0.05

#: 字体回退链（正文）。glyph 找不到 Semibold 家族时退回这里 + bold。
_FONT_STACK = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI Variable Text",
    "Segoe UI",
    "TkDefaultFont",
)


def _mix(colour: str, other: str, ratio: float) -> str:
    """把 ``colour`` 按 ``ratio`` 向 ``other`` 混合（用于派生态颜色）。"""
    first = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    second = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [int(round(a + (b - a) * ratio)) for a, b in zip(first, second)]
    return "#" + "".join(f"{value:02X}" for value in mixed)


@dataclass(frozen=True)
class Palette:
    name: str
    background: str
    surface: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_secondary: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    error: str
    warning: str
    selection: str
    track: str
    scrollbar: str
    scrollbar_hover: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    @property
    def text_disabled(self) -> str:
        """禁用态文字：正文向底色靠 55%（比次要信息更淡，但还能读）。"""
        return _mix(self.text, self.background, 0.55)


LIGHT = Palette(
    name="light",
    background="#F3F4F6",
    surface="#FFFFFF",
    surface_hover="#E9EBEF",
    border="#D7DAE0",
    border_strong="#B4BAC4",
    text="#000000",
    text_secondary="#5D5D5D",
    accent="#0067C0",
    accent_hover="#005BA8",
    accent_text="#FFFFFF",
    success="#0F7B0F",
    error="#C42B1C",
    warning="#9D5D00",
    selection="#CCE4F7",
    track="#DFE2E7",
    scrollbar="#C7CBD3",
    scrollbar_hover="#A9AFBA",
)

DARK = Palette(
    name="dark",
    background="#191919",
    surface="#2B2B2B",
    surface_hover="#363636",
    border="#3F3F3F",
    border_strong="#565656",
    text="#FFFFFF",
    text_secondary="#B0B0B0",
    accent="#4CC2FF",
    accent_hover="#6FCEFF",
    accent_text="#0A0A0A",
    success="#6CCB5F",
    error="#FF99A4",
    warning="#FCE100",
    selection="#2C4A63",
    track="#333333",
    scrollbar="#4A4A4A",
    scrollbar_hover="#5E5E5E",
)


def system_uses_dark() -> bool:
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            key.Close()
        return int(value) == 0
    except OSError:
        return False


def pick_palette(override: Optional[str] = None) -> Palette:
    """``override`` 可取 ``"light"`` / ``"dark"``，默认跟随系统。"""
    if override == "dark":
        return DARK
    if override == "light":
        return LIGHT
    return DARK if system_uses_dark() else LIGHT


class Metrics:
    """DPI 换算的唯一入口：逻辑像素 → 物理像素。"""

    def __init__(self, root: tk.Misc):
        self.root = root
        try:
            dpi = float(root.winfo_fpixels("1i"))
        except tk.TclError:  # pragma: no cover
            dpi = 96.0
        self.dpi = int(round(dpi)) or 96
        try:
            root.tk.call("tk", "scaling", self.dpi / 72.0)
        except tk.TclError:  # pragma: no cover
            pass

    def px(self, value: float) -> int:
        return int(round(value * self.dpi / 96.0))


class Fonts:
    """全局字体（正文字体由系统中文 UI 字体承担，回退链见 ``_FONT_STACK``）。"""

    def __init__(self, root: tk.Misc):
        self.family = self._pick_family(root)
        self.body = tkfont.Font(root=root, name="QfeBody", family=self.family,
                                size=FONT_BODY_PT)
        self.small = tkfont.Font(root=root, name="QfeSmall", family=self.family,
                                 size=FONT_SMALL_PT)
        self.section = tkfont.Font(root=root, name="QfeSection", family=self.family,
                                   size=FONT_BODY_PT, weight="bold")
        self.bold = tkfont.Font(root=root, name="QfeBold", family=self.family,
                                size=FONT_BODY_PT, weight="bold")
        # 单字符图标（如帮助的“?”）：字号按图标视觉高度给，和齿轮等大；
        # 字重要“中间态”，所以家族优先用带 Semibold 档的那个（见 GLYPH_* 常量）
        glyph_family, glyph_weight = self._pick_glyph(root)
        self.glyph_px = self._glyph_pixels(root)
        self.glyph = tkfont.Font(root=root, name="QfeGlyph", family=glyph_family,
                                 size=-self.glyph_px, weight=glyph_weight)
        self.mono = tkfont.Font(root=root, name="QfeMono", family="Consolas",
                                size=FONT_SMALL_PT)
        # 语言按钮的“CN / EN”：正文字体 + 加粗，字号比正文大一号，
        # 让两三个字母的墨迹高度和旁边 20 逻辑像素的主题图标齐平
        self.lang_text = tkfont.Font(root=root, name="QfeLang", family=self.family,
                                     size=FONT_BODY_PT + 4, weight="bold")
        # 让没有显式指定字体的控件（tk.Text / 原生对话框）跟随同一套
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                named = tkfont.nametofont(name, root=root)
                named.configure(family=self.family, size=FONT_BODY_PT)
            except (tk.TclError, KeyError):  # pragma: no cover
                pass

    @property
    def glyph_dy(self) -> int:
        """“?”在行框里偏低，画的时候按字号往上挪回来（实测墨迹中心低约 5% 字号）。

        Tk 的 Canvas 文本按**行框**居中（ascent+descent），不是按字形墨迹居中；
        Segoe 的“?”墨迹落在行框下半部，不挪的话按钮里看着偏下。
        """
        return -int(round(self.glyph_px * GLYPH_NUDGE_RATIO))

    @staticmethod
    def _glyph_pixels(root: tk.Misc) -> int:
        """``GLYPH_PT`` 换算成整数像素字号（Tk 的 point 字号必须是整数）。"""
        try:
            scaling = float(root.tk.call("tk", "scaling"))
        except (tk.TclError, ValueError):  # pragma: no cover - 极端精简的 Tk 构建
            scaling = 96.0 / 72.0
        return max(1, int(round(GLYPH_PT * scaling)))

    @staticmethod
    def _pick_glyph(root: tk.Misc) -> tuple:
        """返回 (家族, 字重)：「比 normal 粗、比 bold 细」的中间态。

        有 ``GLYPH_FAMILY``（Segoe UI Semibold）就用它 + normal；没有就退回正文家族，
        并按 bold 兜底——宁可粗一点也不让“?”细到看不清。
        """
        available = set(tkfont.families(root))
        if GLYPH_FAMILY in available:
            return GLYPH_FAMILY, "normal"
        return Fonts._pick_family(root), "bold"

    @staticmethod
    def _pick_family(root: tk.Misc) -> str:
        available = set(tkfont.families(root))
        for candidate in _FONT_STACK:
            if candidate in available:
                return candidate
        return "TkDefaultFont"

    def measure(self, text: str) -> int:
        return int(self.body.measure(text))


def apply_ttk_styles(root: tk.Misc, palette: Palette, fonts: Fonts,
                     metrics: Metrics) -> ttk.Style:
    """把 ttk（clam）主题改成调色板里的样子。

    放在这里而不是散在窗口代码里：换主题只改 ``palette`` 一个对象。
    """
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover - 极端精简的 Tk 构建
        pass
    px = metrics.px

    style.configure(
        ".",
        background=palette.background,
        foreground=palette.text,
        font=fonts.body,
        focuscolor=palette.accent,
        bordercolor=palette.border,
    )
    style.configure("TFrame", background=palette.background)
    style.configure("Card.TFrame", background=palette.surface,
                    bordercolor=palette.border, relief="solid", borderwidth=1)
    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure("Secondary.TLabel", background=palette.background,
                    foreground=palette.text_secondary, font=fonts.small)
    style.configure("Section.TLabel", background=palette.background,
                    foreground=palette.text, font=fonts.section)

    # ---- 按钮 -------------------------------------------------------------
    # ⚠️ clam 主题给 TButton 的默认 -width 是 -11（11 个字符的最小宽度），
    # 结果是"刷新"和"脱机→联机"被拉成同一个宽度、整排按钮都虚胖。
    # 统一改成 0 = 按文字自然宽度。
    button_padding = (px(12), px(6))
    style.configure(
        "TButton",
        width=0,
        background=palette.surface,
        foreground=palette.text,
        bordercolor=palette.border_strong,
        lightcolor=palette.surface,
        darkcolor=palette.surface,
        focuscolor=palette.accent,
        focusthickness=1,
        relief="flat",
        padding=button_padding,
        font=fonts.body,
    )
    style.map(
        "TButton",
        background=[("disabled", palette.surface), ("pressed", palette.surface_hover),
                    ("active", palette.surface_hover)],
        foreground=[("disabled", palette.text_disabled)],
        bordercolor=[("disabled", palette.border), ("active", palette.border_strong)],
        lightcolor=[("active", palette.surface_hover)],
        darkcolor=[("active", palette.surface_hover)],
    )
    # 强调色只给"推荐的那一个动作"
    style.configure(
        "Accent.TButton",
        width=0,
        background=palette.accent,
        foreground=palette.accent_text,
        bordercolor=palette.accent,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        focuscolor=palette.accent_text,
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", palette.surface), ("pressed", palette.accent_hover),
                    ("active", palette.accent_hover)],
        foreground=[("disabled", palette.text_disabled)],
        bordercolor=[("disabled", palette.border)],
        lightcolor=[("active", palette.accent_hover)],
        darkcolor=[("active", palette.accent_hover)],
    )
    # 工具条上的开关/次要动作：常态是"白色小按钮"，选中态用选中色
    style.configure(
        "Tool.TButton",
        width=0,
        background=palette.surface,
        foreground=palette.text,
        bordercolor=palette.border,
        lightcolor=palette.surface,
        darkcolor=palette.surface,
        padding=(px(10), px(5)),
    )
    style.configure(
        "ToolBold.TButton",
        width=0,
        background=palette.surface,
        foreground=palette.text,
        bordercolor=palette.border,
        lightcolor=palette.surface,
        darkcolor=palette.surface,
        padding=(px(10), px(5)),
        font=fonts.bold,
    )
    style.map(
        "ToolBold.TButton",
        background=[("disabled", palette.background), ("pressed", palette.surface_hover),
                    ("active", palette.surface_hover)],
        foreground=[("disabled", palette.text_disabled)],
        bordercolor=[("disabled", palette.border), ("active", palette.border_strong)],
    )
    style.map(
        "Tool.TButton",
        background=[("disabled", palette.background), ("selected", palette.selection),
                    ("pressed", palette.surface_hover), ("active", palette.surface_hover)],
        foreground=[("disabled", palette.text_disabled)],
        bordercolor=[("disabled", palette.border), ("selected", palette.accent)],
    )

    # ---- 表格 -------------------------------------------------------------
    style.configure(
        "Treeview",
        background=palette.surface,
        fieldbackground=palette.surface,
        foreground=palette.text,
        bordercolor=palette.border,
        lightcolor=palette.border,
        darkcolor=palette.border,
        borderwidth=1,
        relief="solid",
        rowheight=px(26),
        font=fonts.body,
    )
    style.map(
        "Treeview",
        background=[("selected", palette.selection)],
        foreground=[("selected", palette.text)],
    )
    style.configure(
        "Treeview.Heading",
        background=palette.background,
        foreground=palette.text_secondary,
        bordercolor=palette.border,
        relief="flat",
        padding=(px(8), px(4)),
        font=fonts.small,
    )
    style.map(
        "Treeview.Heading",
        background=[("active", palette.surface_hover)],
        foreground=[("active", palette.text)],
    )

    # ---- 进度条 -----------------------------------------------------------
    style.configure(
        "Horizontal.TProgressbar",
        background=palette.accent,
        troughcolor=palette.track,
        bordercolor=palette.track,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        thickness=px(4),
    )

    # ---- 滚动条：不要箭头，只有一条 thumb ---------------------------------
    for orient in ("Vertical", "Horizontal"):
        style.layout(
            f"{orient}.TScrollbar",
            [(f"{orient}.Scrollbar.trough",
              {"children": [(f"{orient}.Scrollbar.thumb", {"expand": "1"})],
               "sticky": "nswe" if orient == "Vertical" else "ew"})],
        )
    style.configure(
        "Vertical.TScrollbar",
        background=palette.scrollbar,
        troughcolor=palette.background,
        bordercolor=palette.background,
        gripcount=0,
        arrowsize=px(6),
        width=px(10),
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("pressed", palette.scrollbar_hover), ("active", palette.scrollbar_hover)],
    )
    return style
