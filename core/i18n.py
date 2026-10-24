"""界面语言的唯一来源：``L("中文", "English")`` 直接写在调用点。

为什么不做成"查表 + 键名"：

* 一条文案只服务一个位置（视觉规范：一条文案只服务一个版位），译文就写在它旁边，
  改文案时不可能忘记另一边；
* 键名表会让人把同一条文案复制到两个键上，翻译就分叉了。

语言只有两种：``zh`` / ``en``。未设置（``""``）或非法值 → 跟随系统 UI 语言。
默认值是 ``zh``：这样单元测试与脚本（不设语言）看到的中文与改动前完全一致。
"""

from __future__ import annotations

import ctypes
import sys

ZH = "zh"
EN = "en"
CHOICES = ("", ZH, EN)          #: "" = 跟随系统

#: Windows 的 LANG_CHINESE（zh-CN / zh-TW / zh-HK 共用这个主语言 ID）
_LANG_CHINESE = 0x04

_current = ZH


def language() -> str:
    """当前生效的语言（``zh`` 或 ``en``）。"""
    return _current


def system_language() -> str:
    """按操作系统的**界面语言**挑一种（不是区域设置）。"""
    if sys.platform == "win32":
        try:
            langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            return ZH if (langid & 0x3FF) == _LANG_CHINESE else EN
        except Exception:  # pragma: no cover - 极老系统 / 非 Windows
            pass
    return ZH if (sys.platform != "win32" and _posix_is_chinese()) else EN


def _posix_is_chinese() -> bool:
    import locale
    try:
        name = locale.getlocale()[0] or ""
    except (ValueError, TypeError):  # pragma: no cover
        return False
    return name.lower().startswith("zh")


def resolve(value: str) -> str:
    """把设置里的值解析成生效语言：``""``/非法 → 系统语言。"""
    if value in (ZH, EN):
        return value
    return system_language()


def set_language(value: str) -> str:
    """设置生效语言，返回解析后的值。"""
    global _current
    _current = resolve(value)
    return _current


def L(zh: str, en: str) -> str:  # noqa: N802 - 调用点要短
    """按当前语言取文案。"""
    return en if _current == EN else zh
