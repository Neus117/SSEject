"""生成工具栏图标与"弹出"按钮图标（构建期用，运行期不依赖 Pillow）。

规则（与经验库一致）：

* 图元描述，不画字体字形；
* 16 倍超采样后平均降采样，边缘平滑；
* 每个图标按 **主题 × 状态 × DPI 档** 预渲染，背景色一起烤进像素——
  Tk 对带 alpha 的图片在半透明边缘上不可靠，按钮悬停换底色时会露出方块；
* 视觉重心：问号、刷新箭头都比几何中心略下/略右。

输出：``assets/icons/<name>-<size>-<theme>-<state>.png``
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "icons")

#: 逻辑尺寸 16 的图标，按常见 DPI 缩放预渲染（1.0~3.0）
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
BASE = 16

#: 与 gui/theme.py 的配色一致：(背景色, 图形色)
THEMES = {
    "light": {"normal": ("#FFFFFF", "#000000"), "accent": ("#0067C0", "#FFFFFF")},
    "dark": {"normal": ("#2B2B2B", "#FFFFFF"), "accent": ("#4CC2FF", "#0A0A0A")},
}

#: 只有"弹出"按钮用强调色底
ACCENT_ICONS = {"eject"}

SUPERSAMPLE = 16


def _gear(draw, box, ink, background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    root, tip = size * 0.30, size * 0.45
    points = []
    for index in range(8):
        centre = 2.0 * math.pi * index / 8
        for offset, radius in ((-0.22, root), (-0.14, tip), (0.14, tip), (0.22, root)):
            angle = centre + offset
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=ink)
    hole = size * 0.135
    draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=background)


def _round_triangle(draw, points, radius, ink, cx, cy):
    """圆角三角形：多边形内缩一点，顶点处画圆补角（圆心也内移，避免外凸）。"""
    inner = [(cx + (x - cx) * 0.93, cy + (y - cy) * 0.93) for x, y in points]
    draw.polygon(inner, fill=ink)
    for x, y in inner:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ink)


def _refresh(draw, box, ink, _background):
    """圆环箭头：缺口在正上方，箭头在右上、沿切线方向。"""
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    radius = size * 0.31
    width = max(1.0, size * 0.095)
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
             start=300, end=240, fill=ink, width=int(round(width)))
    # 箭头：底边垂直于切线，尖端沿切线，底边中心落在弧端点上
    import math as _math
    angle = _math.radians(300)
    px_, py_ = cx + radius * _math.cos(angle), cy + radius * _math.sin(angle)
    tx, ty = -_math.sin(angle), _math.cos(angle)
    nx, ny = _math.cos(angle), _math.sin(angle)
    head_len, head_half = size * 0.19, size * 0.075
    draw.polygon([
        (px_ + nx * head_half, py_ + ny * head_half),
        (px_ - nx * head_half, py_ - ny * head_half),
        (px_ + tx * head_len, py_ + ty * head_len),
    ], fill=ink)


def _help(draw, box, ink, _background):
    """问号：上方钩 + 短斜颈 + 竖茎 + 圆点（笔画用圆头补角，接缝不出缺口）。"""
    import math as _math
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx = (x0 + x1) / 2.0
    width = max(1.0, size * 0.105)
    hook_r = size * 0.175
    hook_cy = y0 + size * 0.32
    draw.arc((cx - hook_r, hook_cy - hook_r, cx + hook_r, hook_cy + hook_r),
             start=200, end=350, fill=ink, width=int(round(width)))
    end_angle = _math.radians(350)
    ex = cx + hook_r * _math.cos(end_angle)
    ey = hook_cy + hook_r * _math.sin(end_angle)
    neck = (cx, y0 + size * 0.47)
    stem_bottom = (cx, y0 + size * 0.62)
    for start_pt, end_pt in ((ex, ey), (neck, None)):
        pass
    draw.line([(ex, ey), neck], fill=ink, width=int(round(width)))
    draw.line([neck, stem_bottom], fill=ink, width=int(round(width)))
    for point in ((ex, ey), neck, stem_bottom):
        draw.ellipse((point[0] - width / 2, point[1] - width / 2,
                      point[0] + width / 2, point[1] + width / 2), fill=ink)
    dot_r = size * 0.070
    dot_y = y0 + size * 0.80
    draw.ellipse((cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r), fill=ink)


PAINTERS = {"gear": _gear, "refresh": _refresh, "help": _help}

def _monitor(draw, box, ink, _background):
    """跟随系统：显示器外框 + 底座。"""
    x0, y0, x1, y1 = box
    size = x1 - x0
    width = max(1.2, size * 0.095)
    left, right = x0 + size * 0.14, x1 - size * 0.14
    top, bottom = y0 + size * 0.24, y1 - size * 0.32
    draw.rectangle((left, top, right, bottom), outline=ink, width=int(round(width)))
    draw.line((x0 + size * 0.36, y1 - size * 0.20, x1 - size * 0.36, y1 - size * 0.20),
              fill=ink, width=int(round(width)))


def _sun(draw, box, ink, _background):
    """浅色：实心圆盘 + 八个小点。"""
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    disc = size * 0.25
    draw.ellipse((cx - disc, cy - disc, cx + disc, cy + disc), fill=ink)
    dot = size * 0.062
    for index in range(8):
        angle = math.radians(index * 45)
        dx = cx + size * 0.43 * math.cos(angle)
        dy = cy + size * 0.43 * math.sin(angle)
        draw.ellipse((dx - dot, dy - dot, dx + dot, dy + dot), fill=ink)


def _moon(draw, box, ink, _background):
    """深色：月牙 = 大圆减去偏移的小圆（用多边形的绕行实现，边缘平滑）。"""
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0 + size * 0.06, (y0 + y1) / 2.0
    r_out, r_in, offset = size * 0.40, size * 0.34, size * 0.20
    a = (r_out ** 2 - r_in ** 2 + offset ** 2) / (2.0 * offset)
    chord = math.sqrt(max(0.0, r_out ** 2 - a ** 2))
    theta = math.atan2(chord, a)
    phi = math.atan2(chord, a - offset)
    points = []
    for index in range(49):
        angle = theta + (2 * math.pi - 2 * theta) * index / 48
        points.append((cx + r_out * math.cos(angle), cy + r_out * math.sin(angle)))
    for index in range(49):
        angle = (2 * math.pi - phi) - (2 * math.pi - 2 * phi) * index / 48
        points.append((cx + offset + r_in * math.cos(angle), cy + r_in * math.sin(angle)))
    draw.polygon(points, fill=ink)


PAINTERS["monitor"] = _monitor
PAINTERS["sun"] = _sun
PAINTERS["moon"] = _moon



def _eject(draw, box, ink, _background=None, app_icon=None):
    """弹出符号：三角形（底角圆角）+ 下方圆角横条，中间留缝。"""
    x0, y0, x1, y1 = box
    size = x1 - x0
    apex = (x0 + size * 0.50, y0 + size * 0.135)
    left = (x0 + size * 0.195, y0 + size * 0.560)
    right = (x0 + size * 0.805, y0 + size * 0.560)
    cx = (apex[0] + left[0] + right[0]) / 3.0
    cy = (apex[1] + left[1] + right[1]) / 3.0
    inner = [(cx + (x - cx) * 0.94, cy + (y - cy) * 0.94)
             for x, y in (apex, left, right)]
    draw.polygon(inner, fill=ink)
    radius = size * 0.055
    for x, y in inner[1:]:                       # 只圆两个底角，顶点保持尖
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ink)
    bar = (x0 + size * 0.195, y0 + size * 0.665,
           x0 + size * 0.805, y0 + size * 0.815)
    draw.rounded_rectangle(bar, radius=int(round(size * 0.050)), fill=ink)


def render(name: str, size: int, background: str, ink: str,
           app_icon: Image.Image) -> Image.Image:
    big = size * SUPERSAMPLE
    canvas = Image.new("RGB", (big, big), background)
    draw = ImageDraw.Draw(canvas)
    box = (0, 0, big, big)
    if name == "eject":
        _eject(draw, box, ink)
    else:
        PAINTERS[name](draw, box, ink, background)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    app_icon = Image.open(os.path.join(HERE, "assets", "app.png"))
    count = 0
    for name in ("gear", "refresh", "help", "eject", "monitor", "sun", "moon"):
        for scale in SCALES:
            size = int(round(BASE * scale))
            for theme_name, states in THEMES.items():
                for state, (background, ink) in states.items():
                    if state == "accent" and name not in ACCENT_ICONS:
                        continue
                    image = render(name, size, background, ink, app_icon)
                    image.save(os.path.join(OUT, f"{name}-{size}-{theme_name}-{state}.png"))
                    count += 1
    print(f"generated {count} icons in {OUT}")


if __name__ == "__main__":
    main()
