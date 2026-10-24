"""使用说明窗口。

窗口标题只写"这件事是什么"（不写程序名——程序名由标题栏图标承担），
与主窗口同一套字体、配色与图标；尺寸按逻辑像素写死，不跟着文本长度涨。
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from core import applog, i18n, version
from core.i18n import L
from gui import win32

#: 窗口尺寸（逻辑像素）
WINDOW_WIDTH = 560
WINDOW_HEIGHT = 470

_HELP_TEXT_ZH = """用途
安全弹出移动磁盘。系统提示“设备正在使用中”时不用改任何设置：选中磁盘点“弹出”，
程序会自动重试，等系统释放后完成移除。

操作步骤
1. 在列表中选择一个磁盘（默认可移动磁盘）。
2. 点“弹出”。如果设备正被其他程序占用，程序会每隔 0.4 秒重试一次，最多约 10 秒。
3. 成功时盘符消失、可以拔下；失败时设备保持原状，等几秒再点一次即可。

说明
· 磁盘操作需要管理员权限；未获得权限时以只读模式运行，仍可查看磁盘。
· 弹出过程不会改动磁盘的联机/脱机状态，重新插回后资源管理器可直接读取。
· “显示所有磁盘”会列出内置磁盘，但内置磁盘不能执行磁盘操作。
· 可按 F5 刷新磁盘列表。
"""

_HELP_TEXT_EN = """What it does
Ejects removable disks safely. When Windows says the device is in use, nothing needs to be
configured: select the disk, click “eject”, and the tool keeps retrying until the system
releases it.

Steps
1. Select a disk in the list (removable disks are listed by default).
2. Click “eject”. If another program is using the device, the tool retries once every
   0.4 seconds, for up to about 10 seconds.
3. On success the drive letter disappears and the device can be unplugged. On failure the
   device is left untouched; wait a few seconds and click once more.

Notes
· Disk operations need administrator rights. Without them the tool runs read-only and can
  still show disks.
· Ejecting never changes the disk's online/offline state; after re-plugging, Explorer reads
  it directly.
· “Show all disks” lists internal disks too, but internal disks cannot be operated on.
· Press F5 to rescan the disk list.
"""

#: 每行开头的“小节标题”（用于加粗样式）；中英文各一套
_SECTION_PREFIXES_ZH = ("用途", "操作步骤", "说明")
_SECTION_PREFIXES_EN = ("What it does", "Steps", "Notes")


def _help_text() -> tuple:
    if i18n.language() == "en":
        return _HELP_TEXT_EN, _SECTION_PREFIXES_EN
    return _HELP_TEXT_ZH, _SECTION_PREFIXES_ZH


class HelpWindow:
    def __init__(self, parent: tk.Misc, *, palette, metrics, fonts, icon_path):
        self.palette = palette
        self.metrics = metrics
        self.fonts = fonts
        self.parent = parent
        px = metrics.px

        window = tk.Toplevel(parent)
        self.window = window
        window.withdraw()
        window.title(L("使用说明", "User guide"))
        window.transient(parent)
        window.resizable(False, False)
        window.configure(background=palette.background)
        window.geometry(f"{px(WINDOW_WIDTH)}x{px(WINDOW_HEIGHT)}")
        window.bind("<Escape>", lambda _event: self._close())

        body = ttk.Frame(window, padding=(px(16), px(16), px(16), px(12)))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        text_wrap = tk.Frame(body, background=palette.background)
        text_wrap.grid(row=0, column=0, sticky="nsew")
        text_wrap.columnconfigure(0, weight=1)
        text_wrap.rowconfigure(0, weight=1)

        text = tk.Text(
            text_wrap, width=40, height=10, wrap="char", relief="flat",
            borderwidth=0, highlightthickness=0, cursor="arrow",
            background=palette.background, foreground=palette.text,
            font=fonts.body, padx=0, pady=0, spacing3=px(4),
        )
        scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        text.tag_configure("h", font=fonts.section, spacing1=px(12), spacing3=px(4))
        text.tag_configure("link", foreground=palette.accent, underline=True)
        text.tag_configure("path", foreground=palette.text_secondary, font=fonts.small)

        help_text, sections = _help_text()
        for line in help_text.splitlines():
            if not line.strip():
                continue
            if line.startswith(sections):
                text.insert("end", line + "\n", ("h",))
            else:
                text.insert("end", line + "\n")

        text.insert("end", L("日志\n", "Log\n"), ("h",))
        text.insert("end", str(applog.log_path()) + "\n", ("path",))
        text.insert("end", L("关于\n", "About\n"), ("h",))
        text.insert("end",
                    f"{version.APP_NAME} {version.version_string()} · "
                    f"{version.LICENSE_NAME}\n",
                    ("path",))
        text.insert("end", version.PROJECT_URL + "\n", ("link",))
        text.tag_bind("link", "<Button-1>",
                      lambda _event: webbrowser.open(version.PROJECT_URL))
        text.tag_bind("link", "<Enter>",
                      lambda _event: text.configure(cursor="hand2"))
        text.tag_bind("link", "<Leave>",
                      lambda _event: text.configure(cursor="arrow"))
        text.configure(state="disabled")
        self.text = text

        footer = ttk.Frame(body)
        footer.grid(row=1, column=0, sticky="e", pady=(px(12), 0))
        # 与对话框按钮同宽一档（单字/双字按钮按自然宽度会比系统对话框窄）
        ttk.Button(footer, text=L("关闭", "Close"), style="Accent.TButton",
                   padding=(px(28), px(6)),
                   command=self._close).pack(side="right")

        win32.set_window_icon(window, icon_path)
        if palette.is_dark:
            win32.set_dark_titlebar(window, True)
        window.update_idletasks()
        # 固定设计尺寸（内容多了用滚动条），deiconify 前算好位置再居中
        self._size = (px(WINDOW_WIDTH), px(WINDOW_HEIGHT))
        self._place_centered()
        window.deiconify()
        self._recenter()
        window.after(60, lambda: self._refresh_chrome(icon_path))
        window.after(120, self._safe_focus)

    def _place_centered(self) -> None:
        """按最终尺寸把说明窗摆在主窗口正中间（deiconify 之前算好，不会跳）。"""
        width, height = self._size
        parent = self.parent
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _recenter(self) -> None:
        """映射后用实际客户区中心再校正一次（标题栏/边框会让第一次估算差几十像素）。"""
        try:
            self.window.update_idletasks()
            parent = self.parent
            parent.update_idletasks()
            dx = (parent.winfo_rootx() + parent.winfo_width() // 2) \
                - (self.window.winfo_rootx() + self.window.winfo_width() // 2)
            dy = (parent.winfo_rooty() + parent.winfo_height() // 2) \
                - (self.window.winfo_rooty() + self.window.winfo_height() // 2)
            if abs(dx) > 1 or abs(dy) > 1:
                self.window.geometry(
                    f"+{self.window.winfo_x() + dx}+{self.window.winfo_y() + dy}"
                )
        except tk.TclError:  # pragma: no cover
            pass

    def _refresh_chrome(self, icon_path) -> None:
        win32.set_window_icon(self.window, icon_path)
        if self.palette.is_dark:
            win32.set_dark_titlebar(self.window, True)

    def _safe_focus(self) -> None:
        # 不 grab_set：说明窗是非模态的，用户可以一边看说明一边操作主窗
        try:
            self.window.focus_force()
        except tk.TclError:  # pragma: no cover
            pass

    def _close(self) -> None:
        self.window.destroy()
