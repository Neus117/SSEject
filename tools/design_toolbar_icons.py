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


def _refresh(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    radius = size * 0.30
    width = max(1.2, size * 0.105)
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
             start=45, end=330, fill=ink, width=int(round(width)))
    draw.polygon([
        (cx + size * 0.155, cy - size * 0.095),
        (cx + size * 0.155, cy + size * 0.215),
        (cx + size * 0.375, cy + size * 0.045),
    ], fill=ink)


def _help(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx = (x0 + x1) / 2.0
    top = y0 + size * 0.10
    width = max(1.2, size * 0.10)
    hook_r = size * 0.165
    hook_cy = top + size * 0.30
    draw.arc((cx - hook_r, hook_cy - hook_r, cx + hook_r, hook_cy + hook_r),
             start=200, end=340, fill=ink, width=int(round(width)))
    draw.line((cx + hook_r * 0.86, hook_cy + hook_r * 0.42, cx, hook_cy + size * 0.30),
              fill=ink, width=int(round(width)))
    dot_r = size * 0.068
    dot_y = top + size * 0.79
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



def _eject(image: Image.Image, box, ink: str, source: Image.Image) -> None:
    """从应用图标取出白色 USB 图形（去掉绿色底板），按目标色重绘。"""
    x0, y0, x1, y1 = box
    size = int(round(x1 - x0))
    scaled = source.convert("RGBA").resize((size, size), Image.LANCZOS)
    rgb = scaled.convert("RGB")
    alpha = scaled.split()[3]
    mask = Image.new("L", (size, size))
    # 只取"接近白色"的像素：绿色底板不能进入掩膜
    values = []
    for (r, g, b), a in zip(rgb.getdata(), alpha.getdata()):
        values.append(255 if (min(r, g, b) >= 200 and a >= 200) else 0)
    mask.putdata(values)
    patch = Image.new("RGB", (size, size), ink)
    image.paste(patch, (int(round(x0)), int(round(y0))), mask)


def render(name: str, size: int, background: str, ink: str,
           app_icon: Image.Image) -> Image.Image:
    big = size * SUPERSAMPLE
    canvas = Image.new("RGB", (big, big), background)
    draw = ImageDraw.Draw(canvas)
    box = (0, 0, big, big)
    if name == "eject":
        _eject(canvas, box, ink, app_icon)
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
