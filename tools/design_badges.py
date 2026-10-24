"""生成对话框提示图标（开发工具，不参与打包）。

为什么预渲染：Tk 的 Canvas **没有抗锯齿**，三角形斜边在多边形填充下必然是
锯齿。这里用 16 倍超采样 + **BOX 平均**降采样（不是 LANCZOS——LANCZOS 会在
对比强的边缘产生振铃，看起来还是硬边），并把三角形三个角做成圆角。

颜色：两种主题统一用暗色主题的明黄 `#FCE100`（用户指定），感叹号用近黑色。
对齐：感叹号对齐三角形**包围盒中心**（不是重心）——用户要的是"垂直居中"。

尺寸按 DPI 生成一组（逻辑边长 36 × 常见缩放），运行期挑最接近的一张，
**不做缩放**（Tk 的 zoom/subsample 是整数倍最近邻，会重新变糊）。

用法::

    python tools/design_badges.py
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "badges"

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
SUPERSAMPLE = 16

#: 逻辑边长
BADGE = 43

#: 错误/信息徽标的圆形底色（警告徽标是黑/白线框，不用这两个颜色）
RED = (196, 43, 28)
BLUE = (0, 103, 192)
WHITE = (255, 255, 255)




def _exclamation(draw: ImageDraw.ImageDraw, s: int, centre_y: float, colour,
                 *, width: float, bar: float, gap: float, dot: float) -> None:
    """在 ``centre_y`` 处垂直居中画感叹号（两条矩形，不用字体字形）。"""
    total = (bar + gap + dot) * s
    top = centre_y - total / 2.0
    half = width * s / 2.0
    x0, x1 = 0.5 * s - half, 0.5 * s + half
    draw.rectangle((x0, top, x1, top + bar * s), fill=colour)
    draw.rectangle((x0, top + (bar + gap) * s, x1, top + (bar + gap + dot) * s),
                   fill=colour)


def warning_geometry(s: float) -> dict:
    """警告三角的几何（**唯一权威**：`gui/dialog.py` 的兜底画法要与这里一致）。

    **等边三角形**（用户要求：原来底 0.85、高 0.85 是等腰，两腰比底长）：
    固定底边 = ``s - 2*margin``，高 = 底 × √3/2 ≈ 0.736 s；再把整枚三角形上移，
    让它的**包围盒**在画布里垂直居中——否则会比同尺寸的圆形徽标看着低一截。

    返回外三角三点、挖空用的内三角三点、重心 y 与线宽（都是画布像素）。
    """
    margin = 0.075 * s
    base = s - 2.0 * margin
    height = base * math.sqrt(3.0) / 2.0
    bottom = s - margin
    top = bottom - height
    shift = (top + bottom) / 2.0 - s / 2.0      # 包围盒居中
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


def _render_warning_outline(img, draw, s: int, background, foreground) -> None:
    """线框警告三角（照搬 GUI-of-Edge-TTS 的 `_dialog_warning_icon`）。

    视觉：实心外三角 + 用底色挖空的内三角 = 均匀粗线框；感叹号是圆头线段 + 圆点，
    整组按三角形**重心**垂直居中。几何全部来自 :func:`warning_geometry`。
    """
    geometry = warning_geometry(s)
    apex = geometry["apex"]
    left = geometry["left"]
    right = geometry["right"]
    inner = geometry["inner"]
    centroid_y = geometry["centroid_y"]
    stroke = geometry["stroke"]
    cx = apex[0]

    draw.polygon([apex, left, right], fill=foreground)
    draw.polygon(inner, fill=background)

    length = 0.20 * s
    gap = 0.060 * s
    dot_radius = 0.050 * s
    total = length + gap + 2.0 * dot_radius
    line_top = centroid_y - total / 2.0
    line_bottom = line_top + length
    dot_y = line_bottom + gap + dot_radius
    half = stroke / 2.0
    draw.rectangle((cx - half, line_top, cx + half, line_bottom), fill=foreground)
    for cap_y in (line_top, line_bottom):
        draw.ellipse((cx - half, cap_y - half, cx + half, cap_y + half), fill=foreground)
    draw.ellipse((cx - dot_radius, dot_y - dot_radius,
                  cx + dot_radius, dot_y + dot_radius), fill=foreground)

def _render(kind: str, size: int, background: Tuple[int, int, int],
            foreground: Tuple[int, int, int] = (0, 0, 0)) -> Image.Image:
    """渲染一枚图标，并把背景色**烤进像素**（输出不透明 RGB）。

    为什么不用透明 PNG：Tk 的 PhotoImage 对"既有 alpha=0 又有半透明"的图
    会丢掉部分透明（实测边缘变成纯色、锯齿回来）。直接把对话框底色合成
    进去，Tk 画的就是最终颜色，抗锯齿一定在。
    """
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), background + (255,))
    draw = ImageDraw.Draw(img)
    s = big

    if kind == "warning":
        _render_warning_outline(img, draw, s, background, foreground)
    elif kind == "error":
        draw.ellipse((0.04 * s, 0.04 * s, 0.96 * s, 0.96 * s), fill=RED)
        _exclamation(draw, s, 0.5 * s, WHITE,
                     width=0.080, bar=0.330, gap=0.070, dot=0.080)
    else:
        draw.ellipse((0.04 * s, 0.04 * s, 0.96 * s, 0.96 * s), fill=BLUE)
        _exclamation(draw, s, 0.5 * s, WHITE,
                     width=0.080, bar=0.330, gap=0.070, dot=0.080)

    return img.convert("RGB").resize((size, size), Image.Resampling.BOX)


#: 对话框底色 / 线条色（与 gui/theme.py 的 background / text 一致）
THEMES = {"light": ((243, 244, 246), (0, 0, 0)), "dark": ((25, 25, 25), (255, 255, 255))}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for kind in ("warning", "error", "info"):
        for scale in SCALES:
            size = int(round(BADGE * scale))
            for theme, (background, foreground) in THEMES.items():
                _render(kind, size, background, foreground).save(
                    OUT / f"{kind}-{size}-{theme}.png")
    files = sorted(OUT.glob("*.png"))
    print(f"wrote {len(files)} files to {OUT}")


if __name__ == "__main__":
    main()
