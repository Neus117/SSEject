# -*- mode: python ; coding: utf-8 -*-
"""SSEject — PyInstaller 打包脚本（单文件、无控制台）。

体积策略（实测 8.9 MB 左右）：
1. 排除这个工具用不到的标准库（ssl/hashlib 会连带 1.9 MB 的 libcrypto DLL）；
2. 丢掉 Tcl/Tk 里用不到的数据目录（时区库、界面翻译、示例图片、Tcl 的 HTTP 包）；
3. 不用 UPX（压缩率有限，还会明显提高杀软误报）。

注意：别排除 ``zipfile`` / ``inspect``（PyInstaller 自己的运行期钩子要用）
和 ``urllib``（``zipfile``→``pathlib`` 会 import 它），否则 exe 一启动就
ModuleNotFoundError。
"""

import os

NAME = "SSEject"
HERE = os.path.abspath(os.getcwd())
ASSETS = os.path.join(HERE, "assets")
ICON = os.path.join(ASSETS, "app.ico")
VERSION_FILE = os.path.join(HERE, "version_info.txt")

#: 整个 assets 目录（主图标 + 对话框徽标 png）作为数据文件带上
DATA_DIRS = [(ASSETS, "assets")] if os.path.isdir(ASSETS) else []

#: tkinter 应用用不到的模块
UNUSED_MODULES = [
    # 网络与加密：会拖进 libcrypto-3-x64.dll
    "ssl", "_ssl", "hashlib", "_hashlib",
    # 并发与数据库
    "asyncio", "multiprocessing", "concurrent", "sqlite3",
    # 压缩/编码里没用到的部分
    "bz2", "lzma", "decimal", "curses",
    # 开发期工具，运行期不需要
    "unittest", "pydoc", "pydoc_data", "doctest", "lib2to3",
    "distutils", "setuptools", "pkg_resources", "pip", "ensurepip", "venv",
    # 示例与教学用包
    "idlelib", "test", "tkinter.test", "turtle", "turtledemo",
    # 本程序自己没用到（日志是手写的）
    "logging", "argparse", "optparse",
]

#: Tcl/Tk 里用不到的数据目录（相对包内路径的前缀）
TRIM_DIRS = (
    "_tcl_data\\tzdata",   # 时区库：日志只显示 HH:MM:SS，用系统时钟
    "_tcl_data\\msgs",     # Tcl 界面翻译
    "_tcl_data\\opt0.4",   # Tcl 选项解析包
    "_tcl_data\\http1.0",  # Tcl 的 HTTP 客户端
    "_tk_data\\msgs",      # Tk 界面翻译
    "_tk_data\\images",    # Tk 示例图片
)


def keep_data(entry) -> bool:
    """数据文件筛选：命中 TRIM_DIRS 前缀的丢掉。"""
    path = str(entry[0]).replace("/", "\\")
    for prefix in TRIM_DIRS:
        if path.startswith(prefix):
            return False
    return True


analysis = Analysis(
    ["app.py"],
    pathex=[HERE],
    binaries=[],
    datas=DATA_DIRS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=UNUSED_MODULES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

analysis.datas = [item for item in analysis.datas if keep_data(item)]

pyz = PYZ(analysis.pure, analysis.zipped_data)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name=NAME,
    icon=ICON if os.path.exists(ICON) else None,
    version=VERSION_FILE if os.path.exists(VERSION_FILE) else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
