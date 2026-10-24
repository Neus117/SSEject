"""版本与产品信息（单一来源）。

SSEject = **S**ure & **S**wift **Eject**：稳、快地把可移动磁盘弹出来。
"""

from .i18n import L

#: 产品名（窗口标题、任务栏、exe 属性都用它）
APP_NAME = "SSEject"

#: 副标题（窗口标题用；随界面语言变）
APP_SUBTITLE_ZH = "可移动磁盘弹出工具"
APP_SUBTITLE_EN = "Portable Disk Eject Tool"

#: 版本号
APP_VERSION = "1.0.0"

#: 项目主页（发布后替换为实际仓库地址）
PROJECT_URL = "https://github.com/Neus117/SSEject"

#: 许可证
LICENSE_NAME = "MIT"


def app_subtitle() -> str:
    """当前语言下的副标题。"""
    return L(APP_SUBTITLE_ZH, APP_SUBTITLE_EN)


def app_title() -> str:
    """窗口标题：产品名 + 当前语言的副标题。"""
    return f"{APP_NAME} {app_subtitle()}"


def version_string() -> str:
    """状态栏 / 帮助窗里显示的版本串。"""
    return f"v{APP_VERSION}"
