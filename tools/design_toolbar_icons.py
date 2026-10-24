"""生成工具栏图标与主题图标（构建期用，运行期不依赖 Pillow）。

图元描述 + 16 倍超采样降采样；按 主题×状态×8 档 DPI 预渲染，底色烤进像素，
输出 assets/icons/<name>-<size>-<theme>-<state>.png。
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "icons")

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
BASE = 20

THEMES = {
    "light": {
        "normal": ("#FFFFFF", "#000000"),
        "hover": ("#E9EBEF", "#000000"),
        "accent": ("#0067C0", "#FFFFFF"),
        "accent_hover": ("#005BA8", "#FFFFFF"),
    },
    "dark": {
        "normal": ("#2B2B2B", "#FFFFFF"),
        "hover": ("#363636", "#FFFFFF"),
        "accent": ("#4CC2FF", "#0A0A0A"),
        "accent_hover": ("#6FCEFF", "#0A0A0A"),
    },
}

ACCENT_ICONS = {"eject"}
PLAIN_STATES = ("normal", "hover")
SUPERSAMPLE = 16

#: 刷新图标（开口圆环 + 折角箭头）的比例，全部来自用户参考图实测。
#: 参考图 505×463、墨迹 374×374（正好是整幅墨迹的边长、圆心在正中）；下表把参考图的
#: 墨迹方框归一化到 0..1，再按“墨迹占图标边长 0.86、四周各留 0.07”映射进图标方框：
#:   * 环外径 = 墨迹边长（1.00）→ 图标内 0.86；线宽 0.102 → 0.088；圆心在正中
#:   * 缺口在右：环从 42° 到 323°（参考图实测），尾巴压住 323° 那一端
#:   * 尾巴是一笔折线，**尖端落在右下角**（参考图：竖线 x 0.898..1.00、横线 y
#:     0.299..0.398；角落即箭尖），两条腿分别向左、向上
REFRESH_SCALE = 0.90                               # 整体缩小 10%（笔画一起缩放）
REFRESH_OUTER = 0.430                              # 环外半径（未缩放的图标方框为单位）
REFRESH_STROKE = 0.100                             # × 缩放 ≈ 0.090 图标边长（≈3.15 px @35px）
REFRESH_ARC = (42, 325)
REFRESH_TAIL = ((0.628, 0.370), (0.886, 0.370), (0.886, 0.113))  # 横尾端 → 箭尖 → 竖顶端

#: 弹出图标（三角 + 横杠）的比例，见 :func:`_eject`
EJECT_APEX_Y, EJECT_BASE_Y, EJECT_HALF_W = 0.125, 0.500, 0.345
EJECT_BAR_Y = (0.646, 0.826)                       # 横杠上下沿（比原来上提 1 px @35px）
EJECT_BAR_RADIUS = 0.055

#: 磁盘图标（“显示全部磁盘”按钮）的比例，见 :func:`_disk`
DISK_SCALE = 1.08                                  # 整体缩放（笔画一起缩放）
DISK_LEFT, DISK_TOP, DISK_RIGHT, DISK_BOTTOM = 0.110, 0.160, 0.890, 0.840
DISK_STROKE, DISK_RADIUS = 0.090, 0.170            # 线宽 × 缩放 ≈ 0.097 图标边长
DISK_SLOT = (0.255, 0.520, 0.380, 0.060)   # 插入槽：x0, x1, y(机身的上 1/3), 线宽
DISK_LED_X, DISK_LED_R = 0.680, 0.060      # 指示灯：圆心 x（与槽同一行）, 半径


def _gear(draw, box, ink, background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    root, tip = size * 0.270, size * 0.387
    points = []
    for index in range(8):
        centre = 2.0 * math.pi * index / 8
        for offset, radius in ((-0.24, root), (-0.15, tip), (0.15, tip), (0.24, root)):
            angle = centre + offset
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=ink)
    hole = size * 0.122
    draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=background)


def _refresh(draw, box, ink, _background):
    """刷新：开口圆环（缺口在右）+ 折角箭头，箭尖落在**右下角**、两腿向左向上。

    结构（与用户参考图一致）：环是一段圆弧；箭头是一笔折线（横尾端 → 箭尖 → 竖顶端），
    所以两条腿一定共用箭尖；箭尖在右下角，横腿向左伸进环里、竖腿向上贴着环的右缘，
    竖腿与环的上端**叠在一起**，看起来是连着的（参考图就是这样连的）。
    折线两个自由端补圆头，等于 round cap；折线用 ``joint="curve"``，箭尖是圆的。

    比例见 ``REFRESH_*`` 常量，全部由参考图 374×374 墨迹实测后按 0.86 映射得到；
    ``REFRESH_SCALE`` 是整体缩放（用户：“有点大了，请缩小 10%”），笔画一起缩放。
    """
    x0, y0, x1, y1 = box
    size = (x1 - x0) * REFRESH_SCALE
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ox, oy = cx - size / 2.0, cy - size / 2.0
    width = max(1, int(round(size * REFRESH_STROKE)))
    # Pillow 的 arc 描边是从给定椭圆框**向内**长出来的（不像 line 那样居中），
    # 所以椭圆半径直接给外径，描边才会落在 REFRESH_OUTER 与 OUTER-STROKE 之间。
    radius = size * REFRESH_OUTER
    draw.arc((cx - radius, cy - radius, cx + radius, cy + radius),
             start=REFRESH_ARC[0], end=REFRESH_ARC[1], fill=ink, width=width)
    points = [(ox + size * px_, oy + size * py_) for px_, py_ in REFRESH_TAIL]
    draw.line(points, fill=ink, width=width, joint="curve")
    half = width / 2.0
    for point in (points[0], points[-1]):  # 两个自由端补圆头
        draw.ellipse((point[0] - half, point[1] - half,
                      point[0] + half, point[1] + half), fill=ink)


def _disk(draw, box, ink, _background):
    """简易磁盘：圆角机身 + 插入槽 + 指示灯。

    全部比例写成常量，一次只调一档；``DISK_SCALE`` 是整体缩放（用户：“现在太小了，
    放大 20%”），笔画跟着一起缩放，等于把整枚图标画大，比例不变。
    机身墨迹 0.78×0.68、线宽 0.10（与刷新同一档）、圆角 0.17；插入槽 y=0.380
    （落在机身的**上 1/3**，用户要求“横向的感叹号稍微往上移”），槽与指示灯同一行。
    按 35px（175% DPI 下的实际按钮图标）算：墨迹约 33×29 px。
    """
    x0, y0, x1, y1 = box
    size = (x1 - x0) * DISK_SCALE          # 放大后的绘图边长
    ox = (x0 + x1) / 2.0 - size / 2.0      # 仍然居中
    oy = (y0 + y1) / 2.0 - size / 2.0
    stroke = max(1, int(round(size * DISK_STROKE)))
    body = (ox + size * DISK_LEFT, oy + size * DISK_TOP,
            ox + size * DISK_RIGHT, oy + size * DISK_BOTTOM)
    draw.rounded_rectangle(body, radius=int(round(size * DISK_RADIUS)),
                           outline=ink, width=stroke)
    slot_x0, slot_x1, slot_y, slot_w = DISK_SLOT
    row_y = oy + size * slot_y
    draw.line((ox + size * slot_x0, row_y, ox + size * slot_x1, row_y),
              fill=ink, width=max(1, int(round(size * slot_w))))
    led_r = size * DISK_LED_R
    led_cx = ox + size * DISK_LED_X
    draw.ellipse((led_cx - led_r, row_y - led_r, led_cx + led_r, row_y + led_r),
                 fill=ink)


def _help(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx = (x0 + x1) / 2.0
    width = max(1.4, size * 0.125)
    hook_r = size * 0.195
    hook_cy = y0 + size * 0.315
    draw.arc((cx - hook_r, hook_cy - hook_r, cx + hook_r, hook_cy + hook_r),
             start=195, end=350, fill=ink, width=int(round(width)))
    end_angle = math.radians(350)
    ex = cx + hook_r * math.cos(end_angle)
    ey = hook_cy + hook_r * math.sin(end_angle)
    neck = (cx, y0 + size * 0.475)
    stem_bottom = (cx, y0 + size * 0.615)
    draw.line([(ex, ey), neck], fill=ink, width=int(round(width)))
    draw.line([neck, stem_bottom], fill=ink, width=int(round(width)))
    for point in ((ex, ey), neck, stem_bottom):
        draw.ellipse((point[0] - width / 2, point[1] - width / 2,
                      point[0] + width / 2, point[1] + width / 2), fill=ink)
    dot_r = size * 0.080
    dot_y = y0 + size * 0.805
    draw.ellipse((cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r), fill=ink)


def _eject(draw, box, ink, _background=None, app_icon=None):
    """弹出：实心三角形 + 下面一条圆角横杠。

    三角形与横杠的间距 = 基准 0.500 与横杠上沿之差（用户要求拉近一点，横杠上提
    1 px @35px 图标 ≈ 0.029 图标边长）。左右对称（0.155 / 0.845），所以水平方向
    天然居中，不必再补偏移。
    """
    x0, y0, x1, y1 = box
    size = x1 - x0
    apex = (x0 + size * 0.50, y0 + size * EJECT_APEX_Y)
    left = (x0 + size * (0.5 - EJECT_HALF_W), y0 + size * EJECT_BASE_Y)
    right = (x0 + size * (0.5 + EJECT_HALF_W), y0 + size * EJECT_BASE_Y)
    # 只填多边形：不再在底角补圆，免得出现两个"肿瘤"般的凸起
    draw.polygon((apex, left, right), fill=ink)
    bar_top, bar_bottom = EJECT_BAR_Y
    bar = (x0 + size * (0.5 - EJECT_HALF_W), y0 + size * bar_top,
           x0 + size * (0.5 + EJECT_HALF_W), y0 + size * bar_bottom)
    draw.rounded_rectangle(bar, radius=int(round(size * EJECT_BAR_RADIUS)), fill=ink)


def _monitor(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    width = max(1.4, size * 0.115)
    left, right = x0 + size * 0.075, x1 - size * 0.075
    top, bottom = y0 + size * 0.175, y1 - size * 0.355
    draw.rectangle((left, top, right, bottom), outline=ink, width=int(round(width)))
    draw.line((x0 + size * 0.315, y1 - size * 0.185, x1 - size * 0.315, y1 - size * 0.185),
              fill=ink, width=int(round(width)))


def _sun(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    disc = size * 0.270
    draw.ellipse((cx - disc, cy - disc, cx + disc, cy + disc), fill=ink)
    dot = size * 0.068
    for index in range(8):
        angle = math.radians(index * 45)
        dx = cx + size * 0.430 * math.cos(angle)
        dy = cy + size * 0.430 * math.sin(angle)
        draw.ellipse((dx - dot, dy - dot, dx + dot, dy + dot), fill=ink)


def _moon(draw, box, ink, _background):
    x0, y0, x1, y1 = box
    size = x1 - x0
    cx, cy = (x0 + x1) / 2.0 + size * 0.055, (y0 + y1) / 2.0
    r_out, r_in, offset = size * 0.425, size * 0.360, size * 0.215
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


PAINTERS = {
    "gear": _gear, "refresh": _refresh, "help": _help, "eject": _eject,
    "monitor": _monitor, "sun": _sun, "moon": _moon, "disk": _disk,
}


def render(name: str, size: int, background: str, ink: str) -> Image.Image:
    big = size * SUPERSAMPLE
    canvas = Image.new("RGB", (big, big), background)
    draw = ImageDraw.Draw(canvas)
    PAINTERS[name](draw, (0, 0, big, big), ink, background)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    count = 0
    for name in PAINTERS:
        for scale in SCALES:
            size = int(round(BASE * scale))
            for theme_name, states in THEMES.items():
                for state, (background, ink) in states.items():
                    accent = state.startswith("accent")
                    if accent and name not in ACCENT_ICONS:
                        continue
                    if not accent and state not in PLAIN_STATES:
                        continue
                    image = render(name, size, background, ink)
                    image.save(os.path.join(OUT, f"{name}-{size}-{theme_name}-{state}.png"))
                    count += 1
    print(f"generated {count} icons in {OUT}")


if __name__ == "__main__":
    main()
