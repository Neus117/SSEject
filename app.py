"""程序入口。

启动流程：DPI 感知 → 提权（可跳过）→ 建主窗口。
提权被拒绝时**不退出**：以只读模式继续，界面里明确写"只读模式"。
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import tkinter as tk
from tkinter import messagebox

from core import admin, applog, disk_query, version
from gui import win32
from gui.dialog import active_dialogs
from gui.help_window import HelpWindow
from gui.main_window import MainWindow


def _install_excepthook():
    """未捕获异常写日志并弹窗——打包成 windowed exe 后 stderr 是看不见的。

    优先用应用自己的对话框（跟主题一致）；它不可用时才退回系统 MessageBox。
    返回值同时挂到 ``root.report_callback_exception``——按钮回调里的异常
    默认只往 stderr 打一行（打包后等于消失），必须也走这条路。
    """
    reporting = {"active": False}

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        applog.write("error", "未捕获异常：\n" + text)
        if reporting["active"]:
            return
        reporting["active"] = True
        try:
            message = (f"{exc_value}\n\n"
                       "详细信息已写入日志文件（帮助 → 打开日志，或界面上的「打开日志」）。")
            dialogs = active_dialogs()
            if dialogs is not None:
                try:
                    dialogs.error("程序出错", message)
                    return
                except Exception:
                    pass
            try:
                messagebox.showerror("程序出错", message)
            except Exception:  # pragma: no cover
                pass
        finally:
            reporting["active"] = False

    sys.excepthook = hook
    return hook


def run_diagnostics(output_path: str) -> int:
    """``--diagnose``：跑一遍真实查询与界面构建，把结果写成 JSON。

    打包成 windowed exe 后没有控制台，出问题只能靠"程序自己说出来"。
    这个模式不弹 UAC，也不会显示窗口。
    """
    result = {
        "version": version.APP_VERSION,
        "admin": admin.has_admin_rights(),
        "icon_path": win32.python_icon_path(),
        "icon_handles": None,
        "disks_total": None,
        "rows": None,
        "rows_show_all": None,
        "badge_px": None,
        "help_window": None,
        "error": None,
    }
    root = None
    try:
        win32.enable_dpi_awareness()
        result["dpi_aware"] = bool(win32.IS_WINDOWS)
        result["disks_total"] = len(disk_query.query_disks(show_all=True))

        root = tk.Tk()
        root.withdraw()
        app = MainWindow(root, admin_state="skipped")
        deadline = time.monotonic() + 20
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        root.update()
        result["rows"] = len(app.tree.get_children())
        # 第二遍打开"显示所有磁盘"，验证表格填充路径（没有可移动磁盘的机器上
        # 第一遍必然是 0 行，只靠它证明不了表格能填）
        app.show_all = True
        app.btn_show_all.state(["selected"])
        app.refresh_disks()
        deadline = time.monotonic() + 20
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.05)
        root.update()
        result["rows_show_all"] = len(app.tree.get_children())
        result["icon_path"] = app.icon_path
        if app.icon_path:
            result["icon_handles"] = [
                win32.load_icon_handle(app.icon_path, 16),
                win32.load_icon_handle(app.icon_path, 32),
            ]
        # 对话框图标是 assets/badges/*.png：打包后能否找到，只有真跑一次才知道
        badge = app.dialogs._badge_image("warning")
        result["badge_px"] = badge.width() if badge is not None else 0
        if badge is not None:
            # 读顶点附近的像素：圆角版本这里应该是底色（三角形从更下面才开始），
            # 尖角版本这里会是填充色。用来确认打包后画的到底是哪一版。
            try:
                result["badge_apex"] = badge.get(badge.width() // 2,
                                                 max(1, int(badge.height() * 0.13)))
            except tk.TclError:  # pragma: no cover
                result["badge_apex"] = None
        help_window = HelpWindow(
            root, palette=app.palette, metrics=app.metrics,
            fonts=app.fonts, icon_path=app.icon_path,
        )
        root.update()
        result["help_window"] = bool(help_window.window.winfo_exists())
        help_window._close()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{exc!r}"
        applog.write("error", "诊断失败：\n" + traceback.format_exc())
    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
    try:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    except OSError:
        return 1
    return 0 if not result["error"] else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--diagnose" in argv:
        index = argv.index("--diagnose")
        target = argv[index + 1] if len(argv) > index + 1 else str(applog.log_dir() / "diagnose.json")
        return run_diagnostics(target)

    win32.enable_dpi_awareness()
    hook = _install_excepthook()

    state = admin.decide_admin_state(argv)
    if state == "relaunched":
        # 新进程已经带着管理员权限启动，本进程退出即可
        return 0
    if state == "denied":
        applog.write("warn", "未获得管理员权限，以只读模式启动")

    root = tk.Tk()
    root.report_callback_exception = hook
    app = MainWindow(root, admin_state=state)
    if state != "admin":
        app._log("未获得管理员权限：可以查看磁盘，但不能执行磁盘操作。", "warn")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
