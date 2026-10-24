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
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "badges"

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
SUPERSAMPLE = 16

#: 逻辑边长
BADGE = 43

#: 警告色：橙黄但色相往明黄靠（#E8A33D 太深，#FCE100 在浅色底上太飘）。
#: 两种主题统一用这一支——浅色下靠饱和度和深色感叹号保证可读性。
YELLOW = (255, 185, 0)          # #FFB900
INK = (32, 31, 30)              # #201F1E 近黑
RED = (196, 43, 28)
BLUE = (0, 103, 192)
WHITE = (255, 255, 255)

#: 三角形三个顶点（画布归一化坐标，等边：底 0.89、高 0.77）
TRIANGLE = ((0.5, 0.095), (0.945, 0.865), (0.055, 0.865))
#: 圆角半径（归一化）。顶点单独用更小的半径：三段式圆角=0.06 时，
#: 60° 的顶点会被削出一小段"平顶"，看起来像被切掉了一块。
CORNER = 0.07
CORNER_APEX = 0.04


def _rounded_polygon(vertices: Sequence[Tuple[float, float]],
                     radius: float,
                     apex_index: int = 0,
                     apex_radius: Optional[float] = None) -> List[Tuple[float, float]]:
    """把多边形顶点替换成"直线段 + 圆角弧"，返回可填充的点列。"""
    points: List[Tuple[float, float]] = []
    count = len(vertices)
    for index, vertex in enumerate(vertices):
        corner_radius = apex_radius if (index == apex_index and apex_radius) else radius
        prev_vertex = vertices[index - 1]
        next_vertex = vertices[(index + 1) % count]
        v1 = (prev_vertex[0] - vertex[0], prev_vertex[1] - vertex[1])
        v2 = (next_vertex[0] - vertex[0], next_vertex[1] - vertex[1])
        len1 = math.hypot(*v1) or 1.0
        len2 = math.hypot(*v2) or 1.0
        u1 = (v1[0] / len1, v1[1] / len1)
        u2 = (v2[0] / len2, v2[1] / len2)
        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        theta = math.acos(dot)
        if theta < 1e-6:
            points.append(vertex)
            continue
        distance = corner_radius / math.tan(theta / 2.0)
        distance = min(distance, len1 * 0.45, len2 * 0.45)
        arc_radius = distance * math.tan(theta / 2.0)
        start = (vertex[0] + u1[0] * distance, vertex[1] + u1[1] * distance)
        end = (vertex[0] + u2[0] * distance, vertex[1] + u2[1] * distance)
        bisector = (u1[0] + u2[0], u1[1] + u2[1])
        length = math.hypot(*bisector) or 1.0
        bisector = (bisector[0] / length, bisector[1] / length)
        centre_distance = arc_radius / math.sin(theta / 2.0)
        centre = (vertex[0] + bisector[0] * centre_distance,
                  vertex[1] + bisector[1] * centre_distance)
        angle_start = math.atan2(start[1] - centre[1], start[0] - centre[0])
        angle_end = math.atan2(end[1] - centre[1], end[0] - centre[0])
        delta = (angle_end - angle_start + math.pi) % (2 * math.pi) - math.pi
        steps = 12
        for step in range(steps + 1):
            angle = angle_start + delta * step / steps
            points.append((centre[0] + arc_radius * math.cos(angle),
                           centre[1] + arc_radius * math.sin(angle)))
    return points


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


def _render_warning_outline(img, draw, s: int, background, foreground) -> None:
    """线框警告三角（照搬 GUI-of-Edge-TTS 的 `_dialog_warning_icon`）。

    视觉：实心外三角 + 用底色挖空的内三角 = 均匀粗线框；感叹号是圆头线段 + 圆点，
    整组按三角形**重心**垂直居中。参数比例来自那个项目（用户已验收过的样子）。
    """
    margin = 0.075 * s
    stroke = 0.062 * s
    cx = s / 2.0
    apex = (cx, margin)
    left = (margin, s - margin)
    right = (s - margin, s - margin)
    centroid_y = (apex[1] + left[1] + right[1]) / 3.0
    scale = max(0.55, 1.0 - (2.4 * stroke) / max(1.0, s - 2.0 * margin))
    inner = [(cx + (x - cx) * scale, centroid_y + (y - centroid_y) * scale)
             for x, y in (apex, left, right)]

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
