"""主窗口。

布局（自上而下，间距全部是 4 的倍数）：

::

    ┌ 磁盘  2 个 · 外接 1 个        [显示所有磁盘] [刷新] [帮助] ┐
    │ 磁盘 | 型号 | 盘符 | 容量 | 类型 | 状态                     │
    │ ...（表格，可伸缩）                                         │
    │ 磁盘 2 · SanDisk · E: · 931 GB · 联机                       │
    │                                                   [弹出] │
    │ 日志                                    [清空] [打开日志]   │
    │ ...（固定高度）                                             │
    │ 就绪                              只读模式   v1.1.0         │
    └─────────────────────────────────────────────────────────────┘

**线程规则**：所有磁盘查询/命令都在 worker 线程里做，worker 只能通过
:meth:`MainWindow._post` 把回调排进主线程队列——Tk 控件不能跨线程碰。
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Callable, List, Optional

from core import applog, disk_query, diskpart_ops, eject, i18n, settings, version
from core.disk_query import DiskInfo
from core.i18n import L
from gui import theme, win32
from gui.dialog import Dialogs
from gui.help_window import HelpWindow
from gui.iconbutton import IconButton
from gui.settings_window import SettingsWindow
from gui.tooltip import Tooltip

#: 日志最多保留的行数
LOG_MAX_LINES = 500

_ACTION_TITLES = {
    "eject": ("确认弹出", "Confirm eject"),
}

_ACTION_CONFIRM = {
    "eject": ("将弹出磁盘 {name}。\n"
              "如果设备正被其他程序占用，程序会等系统释放后自动重试（最多约 10 秒），"
              "不会改动磁盘的联机/脱机状态。\n"
              "未保存的数据可能丢失，继续？",
              "Disk {name} will be ejected.\n"
              "If another program is using it, the tool retries automatically for up to "
              "10 seconds and never changes the disk's online/offline state.\n"
              "Unsaved data may be lost. Continue?"),
}


class MainWindow:
    def __init__(self, root: tk.Tk, *, admin_state: str = "admin"):
        self.root = root
        self.admin = admin_state == "admin"
        self.user_settings = settings.load()
        i18n.set_language(self.user_settings.get("language", ""))
        self.palette = theme.pick_palette(self._theme_override())
        self.metrics = theme.Metrics(root)
        self.fonts = theme.Fonts(root)
        theme.apply_ttk_styles(root, self.palette, self.fonts, self.metrics)
        self.icon_path = win32.python_icon_path()
        self.dialogs = Dialogs(root, palette=self.palette, metrics=self.metrics,
                               fonts=self.fonts, icon_path=self.icon_path)

        self.show_all = False
        self.busy = False
        self._alive = True
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._tooltips: List[Tooltip] = []
        self._icon_images = {}
        self._log_history = []
        self._help: Optional[HelpWindow] = None
        self._last_disks: Optional[List[DiskInfo]] = None

        self._build_ui()
        self._apply_window_chrome()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F5>", lambda _event: self.refresh_disks())
        self._poll_queue()
        self.refresh_disks()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        px = self.metrics.px
        palette = self.palette
        self.root.configure(background=palette.background)
        self.root.title(version.app_title())
        self.root.minsize(px(theme.WINDOW_MIN_WIDTH), px(theme.WINDOW_MIN_HEIGHT))
        self.root.geometry(f"{px(theme.WINDOW_WIDTH)}x{px(theme.WINDOW_HEIGHT)}")

        content = ttk.Frame(self.root, padding=(px(theme.SPACE_3), px(theme.SPACE_3),
                                                px(theme.SPACE_3), px(theme.SPACE_2)))
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)  # 窗口拉高时多出来的空间给日志

        self._build_header(content, px)

        # 磁盘表：最少 5 行、按条数长高，最多 7 行，再多就滚动
        self.top_frame = ttk.Frame(content)
        self.top_frame.grid(row=1, column=0, sticky="ew")
        self.top_frame.columnconfigure(0, weight=1)

        # 日志：固定初始高度，内容多了用滚动条
        self.log_frame = ttk.Frame(content)
        self.log_frame.grid(row=2, column=0, sticky="nsew")
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)

        self._build_table(self.top_frame, px)
        self._build_log(self.log_frame, px)
        self._build_status(content, px)

    def _theme_override(self) -> Optional[str]:
        mode = self.user_settings.get("theme", "system")
        return None if mode == "system" else mode

    def _icon_size(self) -> int:
        target = self.metrics.px(20)
        return min((20, 25, 30, 35, 40, 45, 50, 60),
                   key=lambda value: (abs(value - target), value))

    def _button_height(self) -> int:
        """图标按钮的高度 = 文字按钮的实际高度（只量一次；用真实的文字按钮做尺子）."""
        if getattr(self, "_btn_height", None) is None:
            probe = ttk.Button(self.root, text="清空", style="Tool.TButton")
            probe.update_idletasks()
            self._btn_height = probe.winfo_reqheight()
            probe.destroy()
        return self._btn_height

    def _load_icon(self, icon: str, size: int, state: str):
        key = (icon, size, state, self.palette.name)
        image = self._icon_images.get(key)
        if image is None:
            image = win32.asset_path(
                "icons", f"{icon}-{size}-{self.palette.name}-{state}.png")
            self._icon_images[key] = image
        return image

    def _icon_button(self, parent, icon: str, *, command, accent: bool = False):
        height = self._button_height()
        size = self._icon_size()
        normal = "accent" if accent else "normal"
        hover = "accent_hover" if accent else "hover"
        width = height * 2 if accent else height
        return IconButton(
            parent, palette=self.palette, metrics=self.metrics,
            icon_paths={
                "normal": self._load_icon(icon, size, normal),
                "hover": self._load_icon(icon, size, hover),
            },
            command=command, width=width, height=height, fonts=self.fonts,
            accent=accent,
        )

    def _build_header(self, parent: ttk.Frame, px) -> None:
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, px(theme.SPACE_2)))
        header.columnconfigure(2, weight=1)

        ttk.Label(header, text=L("磁盘", "Disks"), style="Section.TLabel").grid(
            row=0, column=0, sticky="w")
        self.count_label = ttk.Label(header, text="—", style="Secondary.TLabel")
        self.count_label.grid(row=0, column=1, sticky="w", padx=(px(theme.SPACE_2), 0))

        # 提示/选中摘要放在标题后面，不再单独占一行
        self.summary_var = tk.StringVar(value=L("选中一个可移动磁盘", "Select a removable disk"))
        ttk.Label(header, textvariable=self.summary_var,
                  style="Secondary.TLabel").grid(
            row=0, column=2, sticky="w", padx=(px(theme.SPACE_3), px(theme.SPACE_2))
        )

        tools = ttk.Frame(header)
        tools.grid(row=0, column=3, sticky="e")

        # 连内置磁盘一起列出：自绘磁盘图标（原来是 "ALL" 文字按钮，字形和其他
        # 图标不搭；现在与刷新/弹出/齿轮同一套 PNG、同一个尺寸）
        self.btn_show_all = self._icon_button(tools, "disk",
                                              command=self._toggle_show_all)
        self.btn_show_all.grid(row=0, column=0, padx=(0, px(8)))
        self.btn_refresh = self._icon_button(tools, "refresh", command=self.refresh_disks)
        self.btn_refresh.grid(row=0, column=1, padx=(0, px(8)))
        # 弹出是主操作：点击区域加宽，图标本身保持原比例（PNG 是正方形）
        self.btn_eject = self._icon_button(tools, "eject", accent=True,
                                           command=lambda: self._start_action("eject"))
        self.btn_eject.grid(row=0, column=2, padx=(0, px(8)))
        self.btn_help = IconButton(
            tools, palette=self.palette, metrics=self.metrics, icon_paths={},
            command=self.show_help, width=self._button_height(),
            height=self._button_height(), fonts=self.fonts,
            text="?", font=self.fonts.glyph, text_dy=self.fonts.glyph_dy,
        )
        self.btn_help.grid(row=0, column=3, padx=(0, px(8)))
        self.btn_settings = self._icon_button(tools, "gear", command=self._open_settings)
        self.btn_settings.grid(row=0, column=4)

        self._tip(self.btn_refresh, L("重新枚举磁盘（F5）", "Re-scan disks (F5)"))
        self._tip(self.btn_show_all,
                  L("连内置磁盘一起列出；内置磁盘不能执行磁盘操作",
                    "List internal disks too; disk operations are limited to external disks"))
        self._tip(self.btn_eject,
                  L("弹出磁盘；被占用时等系统释放并自动重试，失败会说明原因",
                    "Eject the disk; retries while the system releases it, and explains any failure"))
        self._tip(self.btn_help, L("使用说明", "User guide"))
        self._tip(self.btn_settings, L("设置", "Settings"))

    def _open_settings(self) -> None:
        if self.busy:
            return
        SettingsWindow(self.root, palette=self.palette, metrics=self.metrics,
                       fonts=self.fonts, icon_path=self.icon_path,
                       theme_mode=self.user_settings.get("theme", "system"),
                       language=self.user_settings.get("language", ""),
                       on_theme=self._apply_theme,
                       on_language=self._apply_language)

    def _apply_theme(self, mode: str) -> None:
        self.user_settings = settings.update(theme=mode)
        self.palette = theme.pick_palette(self._theme_override())
        theme.apply_ttk_styles(self.root, self.palette, self.fonts, self.metrics)
        self.dialogs = Dialogs(self.root, palette=self.palette, metrics=self.metrics,
                               fonts=self.fonts, icon_path=self.icon_path)
        self._rebuild()

    def _apply_language(self, mode: str) -> None:
        self.user_settings = settings.update(language=mode)
        i18n.set_language(mode)
        self._rebuild()

    def _rebuild(self) -> None:
        """按当前主题/语言重建界面；不重新枚举磁盘（用上一次的查询结果）。"""
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        self._refresh_chrome()
        self._restore_log()
        if getattr(self, "_last_disks", None) is not None:
            self._refresh_done(self._last_disks, [], quiet=True)

    def _restore_log(self) -> None:
        history, self._log_history = self._log_history, []
        for message, level, with_time in history:
            self._log(message, level, with_time=with_time)

    def _build_table(self, parent: ttk.Frame, px) -> None:
        wrapper = ttk.Frame(parent)
        wrapper.grid(row=0, column=0, sticky="nsew", pady=(0, px(theme.SPACE_2)))
        wrapper.columnconfigure(0, weight=1)
        wrapper.rowconfigure(0, weight=1)

        columns = ("disk", "model", "letters", "size", "type", "state")
        self.tree = ttk.Treeview(
            wrapper, columns=columns, show="headings", selectmode="browse",
            height=5,  # 最少 5 行；有磁盘时按条数增长（见 _refresh_done）
        )
        headings = {
            "disk": (L("磁盘", "Disk"), 56, "center"),
            "model": (L("型号", "Model"), 260, "w"),
            "letters": (L("盘符", "Drive"), 80, "center"),
            "size": (L("容量", "Size"), 96, "e"),
            "type": (L("类型", "Type"), 64, "center"),
            "state": (L("状态", "State"), 64, "center"),
        }
        for key, (text, width, anchor) in headings.items():
            self.tree.heading(key, text=text, anchor=anchor)
            stretch = key == "model"
            self.tree.column(
                key, width=px(width),
                minwidth=px(120) if stretch else px(48),
                anchor=anchor, stretch=stretch,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.empty_label = ttk.Label(wrapper, text="", justify="center",
                                     style="Secondary.TLabel", background=self.palette.surface,
                                     wraplength=px(480))

    def _build_log(self, parent: ttk.Frame, px) -> None:
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, px(theme.SPACE_1)))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=L("日志", "Log"),
                  style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.btn_clear_log = ttk.Button(header, text=L("清空", "Clear"), style="Tool.TButton",
                                        command=self._clear_log)
        self.btn_clear_log.grid(row=0, column=1, sticky="e")
        self.btn_open_log = ttk.Button(header, text=L("打开日志", "Open log"), style="Tool.TButton",
                                       command=self._open_log)
        self.btn_open_log.grid(row=0, column=2, sticky="e",
                               padx=(px(theme.SPACE_2), 0))

        card = tk.Frame(parent, background=self.palette.border, padx=1, pady=1)
        card.grid(row=1, column=0, sticky="nsew")
        self.log_text = tk.Text(
            card, height=7, wrap="word", relief="flat", borderwidth=0,
            background=self.palette.surface, foreground=self.palette.text,
            font=self.fonts.small, padx=px(theme.SPACE_2), pady=px(theme.SPACE_1),
            highlightthickness=0, state="disabled", cursor="arrow",
        )
        self.log_scroll = ttk.Scrollbar(card, orient="vertical",
                                        command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("time", foreground=self.palette.text_secondary)
        self.log_text.tag_configure("info", foreground=self.palette.text)
        self.log_text.tag_configure("ok", foreground=self.palette.success)
        self.log_text.tag_configure("warn", foreground=self.palette.warning)
        self.log_text.tag_configure("error", foreground=self.palette.error)

    def _build_status(self, parent: ttk.Frame, px) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=3, column=0, sticky="ew", pady=(px(theme.SPACE_2), 0))
        bar.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value=L("就绪", "Ready"))
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        # 进度条固定宽度放在中间：显示/隐藏不会挤动右边的标签
        self.spinner_holder = tk.Frame(bar, width=px(72), height=px(8),
                                       background=self.palette.background)
        self.spinner_holder.grid(row=0, column=1, sticky="w", padx=(px(theme.SPACE_3), 0))
        self.spinner_holder.grid_propagate(False)
        self.spinner = ttk.Progressbar(self.spinner_holder, mode="indeterminate",
                                       style="Horizontal.TProgressbar")
        self.spinner.place(x=0, y=px(2), relwidth=1.0)
        self.spinner.place_forget()

        self.admin_label = ttk.Label(
            bar,
            text=L("管理员", "Administrator") if self.admin else L("只读模式", "Read-only"),
            style="Secondary.TLabel",
            foreground=self.palette.success if self.admin else self.palette.warning,
        )
        self.admin_label.grid(row=0, column=2, sticky="e", padx=(0, px(theme.SPACE_3)))
        ttk.Label(bar, text=f"v{version.APP_VERSION}",
                  style="Secondary.TLabel").grid(row=0, column=3, sticky="e")
        if not self.admin:
            self._tip(self.admin_label,
                      L("未获得管理员权限：可以查看磁盘，但不能执行磁盘操作",
                        "No administrator rights: disks can be viewed but not operated on"))

    def _tip(self, widget, text: str) -> None:
        self._tooltips.append(
            Tooltip(widget, text, palette=self.palette,
                    metrics=self.metrics, fonts=self.fonts)
        )

    def _apply_window_chrome(self) -> None:
        self.root.update_idletasks()
        self._refresh_chrome()
        # 窗口映射之后再设一次：未映射时拿到的句柄不一定是真正的顶层窗口，
        # 深色标题栏会"设了但没生效"。
        self.root.after(60, self._refresh_chrome)

    def _refresh_chrome(self) -> None:
        if not self._alive:
            return
        win32.set_window_icon(self.root, self.icon_path)
        # 深→浅也必须显式设回浅色标题栏，否则标题栏会停在上一次的颜色
        win32.set_dark_titlebar(self.root, self.palette.is_dark)

    # -------------------------------------------------------------- 线程 --
    def _post(self, callback: Callable, *args, **kwargs) -> None:
        self._queue.put((callback, args, kwargs))

    def _poll_queue(self) -> None:
        if not self._alive:
            return
        try:
            while True:
                callback, args, kwargs = self._queue.get_nowait()
                try:
                    callback(*args, **kwargs)
                except Exception as exc:  # pragma: no cover - 界面回调兜底
                    applog.write("error", L(f"界面回调异常：{exc!r}", f"UI callback failed: {exc!r}"))
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)

    # -------------------------------------------------------------- 刷新 --
    def _toggle_show_all(self) -> None:
        self.show_all = not self.show_all
        self.btn_show_all.set_selected(self.show_all)
        self.refresh_disks()

    def refresh_disks(self) -> None:
        if self.busy:
            return
        show_all = self.show_all
        self._set_busy(True, L("正在刷新磁盘…", "Scanning disks…"))
        self._log(L("开始刷新磁盘…", "Scanning disks…"), "info")

        def worker() -> None:
            try:
                disks = disk_query.query_disks(show_all=show_all)
                # 外接盘如果被留在脱机状态，资源管理器读不到它。
                # 用户要的是"插回来就能用"，所以这里自动恢复联机（只动外接盘）。
                recovered = []
                if self.admin:
                    for disk in disks:
                        if disk.is_external and disk.is_offline:
                            try:
                                diskpart_ops.online_disk(disk.index)
                            except Exception:  # noqa: BLE001 - 恢复失败不阻断刷新
                                continue
                            recovered.append(disk.index)
                    if recovered:
                        disks = disk_query.query_disks(show_all=show_all)
            except Exception as exc:  # noqa: BLE001 - 任何失败都要变成界面提示
                self._post(self._refresh_failed, exc)
            else:
                self._post(self._refresh_done, disks, recovered)

        threading.Thread(target=worker, daemon=True, name="qfe-refresh").start()

    def _refresh_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self._log(L(f"刷新失败：{error}", f"Scan failed: {error}"), "error")
        self.status_var.set(L("刷新失败", "Scan failed"))
        self.dialogs.error(L("刷新失败", "Scan failed"), str(error))

    def _refresh_done(self, disks: List[DiskInfo],
                      recovered: Optional[List[int]] = None,
                      quiet: bool = False) -> None:
        self._last_disks = list(disks)
        for index in recovered or []:
            self._log(L(f"磁盘 {index} 之前处于脱机状态，已自动恢复联机",
                          f"Disk {index} was left offline and has been set online again"), "ok")
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for disk in disks:
            self.tree.insert(
                "", "end", iid=str(disk.index),
                values=(disk.index, disk.model or "—", disk.letters_text,
                        disk.size_text, disk.type_text, disk.state_text),
            )
        # 高度随内容走，但最少 5 行；再多就滚动
        self.tree.configure(height=max(5, min(len(disks), 7)))
        for iid in previous:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                break

        external = sum(1 for disk in disks if disk.is_external)
        if self.show_all:
            self.count_label.configure(
                text=L(f"{len(disks)} 个 · 外接 {external} 个",
                        f"{len(disks)} total · {external} external"))
        else:
            self.count_label.configure(text=L(f"{len(disks)} 个", f"{len(disks)}"))
        self._set_busy(False)
        self.status_var.set(L("就绪", "Ready"))
        self._update_empty_state(disks)
        self._update_summary()
        if quiet:
            return
        if disks:
            self._log(L(f"已刷新：找到 {len(disks)} 个磁盘。",
                      f"Scan finished: {len(disks)} disk(s) found."), "ok")
        elif self.show_all:
            self._log(L("已刷新：没有找到任何磁盘。", "Scan finished: no disks found."), "warn")
        else:
            self._log(L("已刷新：没有可移动磁盘。可点「显示所有磁盘」查看全部磁盘。",
                      "Scan finished: no removable disks. Use “show all disks” to list every disk."),
                  "warn")
        # 外接盘没有盘符时在资源管理器里看不到，但磁盘本身是好的——要说清楚
        for disk in disks:
            if disk.is_external and not disk.letters:
                self._log(
                    L(f"磁盘 {disk.index} 当前没有盘符，资源管理器里不会显示；"
                      "可在“磁盘管理”里为它分配盘符。",
                      f"Disk {disk.index} has no drive letter, so Explorer will not show it; "
                      "assign one in “Disk Management”."),
                    "warn",
                )

    def _update_empty_state(self, disks: List[DiskInfo]) -> None:
        if disks:
            self.empty_label.place_forget()
            return
        orphans = disk_query.orphan_letters()
        if self.show_all:
            text = L("没有检测到磁盘", "No disks detected")
        else:
            text = L("没有检测到可移动磁盘\n插入设备后点「刷新」\n\n"
                     "也可以点「显示所有磁盘」查看全部磁盘",
                     "No removable disk detected\nPlug in a device, then click “refresh”\n\n"
                     "You can also click “show all disks” to list every disk")
        if orphans:
            separator = "、" if i18n.language() == "zh" else ", "
            letters = separator.join(f"{letter}:" for letter in orphans)
            text += L(f"\n\n检测到盘符 {letters} 没有对应的磁盘：设备可能已被移除、"
                      "卷还没清理，重启或重新插拔后会恢复正常",
                      f"\n\nDrive letter(s) {letters} have no disk behind them: the device may "
                      "be gone or the volume not cleaned up; restarting or re-plugging fixes it")
        self.empty_label.configure(text=text)
        # 在表头以下的区域里垂直居中：rely 以整个框为基准，补半行抵消表头
        self.empty_label.place(relx=0.5, rely=0.5, anchor="center",
                               y=self.metrics.px(theme.ROW_HEIGHT // 2))
        self.empty_label.lift()
        if orphans:
            separator = "、" if i18n.language() == "zh" else ", "
            self._log(
                L("检测到没有对应磁盘的盘符：", "Drive letters without a disk: ")
                + separator.join(f"{letter}:" for letter in orphans)
                + L("（通常是设备已移除、卷未清理；重启或重新插拔即可恢复）",
                    " (usually the device is gone and the volume not cleaned up; "
                    "restart or re-plug to recover)"),
                "warn",
            )

    # -------------------------------------------------------------- 选择 --
    def _selected_disk(self) -> Optional[DiskInfo]:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            index = int(selection[0])
        except ValueError:
            return None
        return disk_query.find_disk_by_index(index)

    def _on_select(self, _event=None) -> None:
        self._update_actions()
        self._update_summary()

    def _update_summary(self) -> None:
        disk = self._selected_disk()
        if disk is None:
            self.summary_var.set(L("选中一个可移动磁盘进行操作", "Select a removable disk to operate on"))
            return
        parts = [L(f"磁盘 {disk.index}", f"Disk {disk.index}"), disk.model or L("未知型号", "Unknown model")]
        if disk.letters:
            parts.append(disk.letters_text)
        parts.append(disk.size_text)
        if disk.is_offline is not None:
            parts.append(L("已脱机", "Offline") if disk.is_offline else L("联机", "Online"))
        self.summary_var.set(" · ".join(parts))

    def _update_actions(self) -> None:
        disk = self._selected_disk()
        usable = (
            bool(disk)
            and disk.is_external
            and self.admin
            and not self.busy
        )
        self._enable(self.btn_eject, usable)

    @staticmethod
    def _enable(button, enabled: bool) -> None:
        if isinstance(button, IconButton):
            button.set_enabled(enabled)
            return
        button.state(["!disabled"] if enabled else ["disabled"])

    # -------------------------------------------------------------- 操作 --
    def _start_action(self, kind: str) -> None:
        if self.busy:
            return
        disk = self._selected_disk()
        if disk is None:
            self.dialogs.info(L("没有选中磁盘", "No disk selected"),
                              L("请先在列表中选择一个磁盘。",
                                "Select a disk in the list first."))
            return
        if not self.admin:
            self.dialogs.warning(
                L("需要管理员权限", "Administrator rights required"),
                L("磁盘操作需要管理员权限。\n"
                  "本次启动未获得权限，只能查看磁盘。\n\n"
                  "请右键程序图标，选择“以管理员身份运行”。",
                  "Disk operations require administrator rights.\n"
                  "This run has no elevation, so disks can only be viewed.\n\n"
                  "Right-click the program icon and choose “Run as administrator”."),
            )
            return
        if not disk.is_external:
            self.dialogs.info(
                L("内置磁盘不能操作", "Internal disks cannot be operated on"),
                L("为防误操作，内置磁盘不能脱机、联机或弹出。",
                  "To prevent mistakes, internal disks cannot be set offline, online "
                  "or ejected."),
            )
            return
        if kind in _ACTION_CONFIRM:
            name = f"{disk.index}（{disk.letters_text}）" if i18n.language() == "zh" \
                else f"{disk.index} ({disk.letters_text})"
            if not self.dialogs.confirm(
                L(*_ACTION_TITLES[kind]), L(*_ACTION_CONFIRM[kind]).format(name=name),
                default_yes=False,
            ):
                return

        self._set_busy(True, self._action_status(kind))
        self._log(L("开始执行：", "Starting: ") + self._action_status(kind).rstrip("…"),
                  "info")

        def worker() -> None:
            started = time.perf_counter()
            try:
                result = self._run_action(kind, disk)
            except Exception as exc:  # noqa: BLE001
                self._post(self._action_failed, kind, disk, exc)
            else:
                elapsed = time.perf_counter() - started
                self._post(self._action_done, kind, disk, result, elapsed)

        threading.Thread(target=worker, daemon=True, name=f"qfe-{kind}").start()

    @staticmethod
    def _action_status(kind: str, lang: str = "") -> str:
        pair = {"eject": ("正在弹出…", "Ejecting…")}[kind]
        return pair[1] if lang == "en" else L(*pair)

    def _run_action(self, kind: str, disk: DiskInfo):
        # 阶段回调走队列回主线程：worker 线程不碰 Tk
        return eject.eject_disk(
            disk, on_stage=lambda text: self._post(self.status_var.set, text)
        )

    def _action_failed(self, kind: str, disk: DiskInfo, error: Exception) -> None:
        self._set_busy(False)
        self.status_var.set(L("操作失败", "Failed"))
        self._log(L(f"磁盘 {disk.index} {self._action_status(kind).rstrip('…')}失败：{error}",
                    f"Disk {disk.index}: {self._action_status(kind, 'en').rstrip('…')} failed: {error}"),
                  "error")
        self.dialogs.error(L("操作失败", "Failed"), str(error))
        self.refresh_disks()

    def _action_done(self, kind: str, disk: DiskInfo, result, elapsed: float) -> None:
        self._set_busy(False)
        success = bool(result.success)
        self._log(
            L(f"磁盘 {disk.index} 弹出{'成功' if success else '未成功'}"
              f"（阶段 {result.stage}，总耗时 {elapsed:.2f} s）",
              f"Disk {disk.index}: eject {'succeeded' if success else 'did not succeed'} "
              f"(stage {result.stage}, {elapsed:.2f} s)"),
            "ok" if success else "warn",
        )
        for line in result.details:
            self._log(line, "info", with_time=False)
        hint = eject.stage_hint(result.stage)
        if hint:
            self._log(hint, "ok" if success else "warn")
        self.status_var.set(L("已弹出", "Ejected") if success
                            else L("弹出未成功", "Eject failed"))
        if not success:
            self.dialogs.warning(L("没能弹出", "Could not eject"),
                                 hint or L("设备仍在使用中。", "The device is still in use."))
        self.refresh_disks()

    # -------------------------------------------------------------- 日志 --
    def _log(self, message: str, level: str = "info", *, with_time: bool = True) -> None:
        self._log_history.append((message, level, with_time))
        applog.write(level, message)
        if not self._alive:
            return
        try:
            self.log_text.configure(state="normal")
            if with_time:
                self.log_text.insert("end", datetime.now().strftime("%H:%M:%S  "), ("time",))
                self.log_text.insert("end", message + "\n", (level,))
            else:
                self.log_text.insert("end", "          " + message + "\n", (level,))
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > LOG_MAX_LINES:
                self.log_text.delete("1.0", f"{line_count - LOG_MAX_LINES}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:  # pragma: no cover - 窗口已销毁
            pass

    def _clear_log(self) -> None:
        self._log_history.clear()
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        except tk.TclError:  # pragma: no cover
            pass

    def _open_log(self) -> None:
        if not applog.open_in_explorer():
            self.dialogs.warning(L("无法打开日志", "Cannot open the log"),
                                 L(f"日志路径：{applog.log_path()}",
                                   f"Log path: {applog.log_path()}"))

    # -------------------------------------------------------------- 状态 --
    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        if text:
            self.status_var.set(text)
        for button in (self.btn_refresh, self.btn_eject, self.btn_help, self.btn_settings):
            self._enable(button, not busy)
        self._enable(self.btn_show_all, not busy)
        if busy:
            self.spinner.place(x=0, y=self.metrics.px(2), relwidth=1.0)
            self.spinner.start(12)
        else:
            self.spinner.stop()
            self.spinner.place_forget()
        self._update_actions()

    def _on_close(self) -> None:
        self._alive = False
        try:
            self.spinner.stop()
        except tk.TclError:  # pragma: no cover
            pass
        self.root.destroy()

    # -------------------------------------------------------------- 帮助 --
    def show_help(self) -> None:
        # 同一时刻只开一个说明窗（重复点“帮助”只是把它提到前面）
        if self._help is not None:
            try:
                if self._help.window.winfo_exists():
                    self._help.window.deiconify()
                    self._help.window.lift()
                    self._help.window.focus_force()
                    return
            except tk.TclError:
                pass
        self._help = HelpWindow(
            self.root,
            palette=self.palette,
            metrics=self.metrics,
            fonts=self.fonts,
            icon_path=self.icon_path,
        )
