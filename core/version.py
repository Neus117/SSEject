"""版本与产品信息（单一来源）。

SSEject = **S**ure & **S**wift **Eject**：稳、快地把可移动磁盘弹出来。
"""

#: 产品名（窗口标题、任务栏、exe 属性都用它）
APP_NAME = "SSEject"

#: 中文副标题
APP_SUBTITLE = "可移动磁盘弹出工具"

#: 窗口标题
APP_TITLE = f"{APP_NAME} {APP_SUBTITLE}"

#: 版本号
APP_VERSION = "1.0.0"

#: 项目主页（发布后替换为实际仓库地址）
PROJECT_URL = "https://github.com/Neus117/SSEject"

#: 许可证
LICENSE_NAME = "MIT"


def version_string() -> str:
    """状态栏 / 帮助窗里显示的版本串。"""
    return f"v{APP_VERSION}"
