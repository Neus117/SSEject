"""核心逻辑的单元测试（不碰真实磁盘）。

运行::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import disk_query, diskpart_ops, eject, winproc  # noqa: E402


class DiskpartStateTest(unittest.TestCase):
    """diskpart 的成败以**最终状态**为准（退出码恒为 0，文案只是兜底）。"""

    SUCCESS_CN = """
Microsoft DiskPart 版本 10.0.19041.964

DISKPART>  select disk 2

磁盘 2 现在是所选磁盘。

DISKPART>  offline disk

DiskPart 成功使磁盘脱机。
"""

    FAILURE_CN = """
Microsoft DiskPart 版本 10.0.19041.964

DISKPART>  select disk 2

磁盘 2 现在是所选磁盘。

DISKPART>  offline disk

DiskPart 遇到错误: 拒绝访问。
有关详细信息，请参阅系统事件日志。
"""

    FAILURE_MISSING_DISK = """
DISKPART>  select disk 9

指定的磁盘不存在。
"""

    @staticmethod
    def _result(text: str) -> winproc.CommandResult:
        return winproc.CommandResult(returncode=0, stdout=text, stderr="")

    def setUp(self):
        """默认把"快路径"都关掉：这些用例只验证 diskpart 兜底的判定逻辑。"""
        for target, name in (
            (diskpart_ops.disk_attr, "set_offline"),
            (diskpart_ops, "_cim_set_offline"),
        ):
            patcher = mock.patch.object(target, name, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_state_offline_means_success(self):
        with mock.patch.object(winproc, "run_diskpart",
                               return_value=self._result(self.SUCCESS_CN)), \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=True):
            output = diskpart_ops.offline_disk(2)
        self.assertIn("成功", output)

    def test_state_still_online_is_an_error_even_without_error_text(self):
        # 输出里没有任何错误字样，但磁盘仍然是联机 —— 照样判失败
        with mock.patch.object(winproc, "run_diskpart",
                               return_value=self._result(self.SUCCESS_CN)), \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=False):
            with self.assertRaises(diskpart_ops.DiskpartError) as ctx:
                diskpart_ops.offline_disk(2)
        self.assertIn("联机", str(ctx.exception))

    def test_access_denied_is_an_error(self):
        with mock.patch.object(winproc, "run_diskpart",
                               return_value=self._result(self.FAILURE_CN)), \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=False):
            with self.assertRaises(diskpart_ops.DiskpartError):
                diskpart_ops.offline_disk(2)

    def test_missing_disk_is_an_error(self):
        # 盘号不存在时磁盘仍然是联机，所以"脱机"这个目标没有达成 → 失败
        with mock.patch.object(winproc, "run_diskpart",
                               return_value=self._result(self.FAILURE_MISSING_DISK)), \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=False):
            with self.assertRaises(diskpart_ops.DiskpartError):
                diskpart_ops.offline_disk(9)

    def test_state_unknown_falls_back_to_error_text(self):
        with mock.patch.object(winproc, "run_diskpart",
                               return_value=self._result(self.FAILURE_CN)), \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=None):
            with self.assertRaises(diskpart_ops.DiskpartError) as ctx:
                diskpart_ops.offline_disk(2)
        self.assertIn("拒绝访问", str(ctx.exception))

    def test_invalid_index_is_rejected_without_running_diskpart(self):
        with mock.patch.object(winproc, "run_diskpart") as runner:
            with self.assertRaises(diskpart_ops.DiskpartError):
                diskpart_ops.offline_disk("2; format")  # type: ignore[arg-type]
        runner.assert_not_called()

    def test_ioctl_offline_skips_diskpart(self):
        with mock.patch.object(diskpart_ops.disk_attr, "set_offline", return_value=True), \
                mock.patch.object(winproc, "run_diskpart") as runner:
            message = diskpart_ops.offline_disk(2)
        runner.assert_not_called()
        self.assertIn("系统接口", message)

    def test_ioctl_offline_failure_falls_back_to_diskpart(self):
        with mock.patch.object(diskpart_ops.disk_attr, "set_offline", return_value=False), \
                mock.patch.object(diskpart_ops, "_cim_set_offline", return_value=None), \
                mock.patch.object(winproc, "run_diskpart",
                                  return_value=self._result(self.SUCCESS_CN)) as runner, \
                mock.patch.object(diskpart_ops, "disk_is_offline", return_value=True):
            diskpart_ops.offline_disk(2)
        runner.assert_called_once()

    def test_ioctl_online_skips_diskpart(self):
        with mock.patch.object(diskpart_ops.disk_attr, "set_offline", return_value=True), \
                mock.patch.object(winproc, "run_diskpart") as runner:
            message = diskpart_ops.online_disk(2)
        runner.assert_not_called()
        self.assertIn("联机", message)

    def test_disk_is_offline_prefers_ioctl(self):
        with mock.patch.object(diskpart_ops.disk_attr, "read_offline", return_value=True), \
                mock.patch.object(winproc, "run_powershell") as ps:
            self.assertTrue(diskpart_ops.disk_is_offline(2))
        ps.assert_not_called()

    def test_disk_is_offline_falls_back_to_powershell(self):
        with mock.patch.object(diskpart_ops.disk_attr, "read_offline", return_value=None), \
                mock.patch.object(winproc, "run_powershell") as ps:
            ps.return_value = winproc.CommandResult(0, "OFFLINE", "")
            self.assertTrue(diskpart_ops.disk_is_offline(2))
        ps.assert_called_once()


class EjectFlowTest(unittest.TestCase):
    def setUp(self):
        """不碰真实卷、也不真的等重试间隔。"""
        sleeper = mock.patch.object(eject.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        budget = mock.patch.object(eject, "SETTLE_BUDGET", 0.0)  # 别在测试里空转 9 秒
        budget.start()
        self.addCleanup(budget.stop)
        eject._SHELL_NOVERB.clear()  # 别让上一个用例的缓存影响本用例

    def test_parse_statuses(self):
        self.assertEqual(
            eject.parse_statuses(["E:INVOKED", "F:NOVERB", "G:RC=0"]),
            {"E": "INVOKED", "F": "NOVERB", "G": "RC=0"},
        )

    def test_clean_letters(self):
        self.assertEqual(eject._clean_letters(["E:", "e", "F:\\", "1"]), ["E", "F"])

    def test_wait_gone_returns_only_vanished_letters(self):
        present = {"E": False, "F": True}
        with mock.patch.object(eject, "letter_present",
                               side_effect=lambda letter: present.get(letter, True)), \
                mock.patch.object(eject.time, "sleep"):
            gone = eject.wait_gone(["E", "F"], timeout=0.01)
        self.assertEqual(gone, ["E"])

    def test_no_verb_still_skips_shell_waiting(self):
        """没有"弹出"动词：Shell 阶段不等待任何盘符；plain 模式不碰磁盘状态。"""
        disk = disk_query.DiskInfo(2, "X", 0, ("H",), True, pnp_id="PNP\\X")
        with mock.patch.object(eject, "shell_status", return_value={"H": "NOVERB"}), \
                mock.patch.object(eject, "wait_gone", return_value=[]) as waiter, \
                mock.patch.object(eject, "letter_present", return_value=True), \
                mock.patch.object(eject, "_safe_remove", return_value=False):
            result = eject.eject_disk(disk)
        self.assertFalse(result.success)
        self.assertIn("没有“弹出”动词", " ".join(result.details))
        self.assertEqual(waiter.call_args_list[0].args[0], [])

    def test_invoked_letter_waits_and_reports_shell_success(self):
        disk = disk_query.DiskInfo(2, "X", 0, ("H",), True, pnp_id="PNP\\X")
        with mock.patch.object(eject, "shell_status", return_value={"H": "INVOKED"}), \
                mock.patch.object(eject, "wait_gone", return_value=["H"]):
            result = eject.eject_disk(disk)
        self.assertTrue(result.success)
        self.assertEqual(result.stage, "shell_com")

    def test_stage_callback_receives_each_stage(self):
        disk = disk_query.DiskInfo(2, "X", 0, ("H",), True, pnp_id="PNP\\X")
        seen = []
        with mock.patch.object(eject, "shell_status", return_value={"H": "NOVERB"}), \
                mock.patch.object(eject, "letter_present", return_value=True), \
                mock.patch.object(eject, "wait_gone", return_value=[]), \
                mock.patch.object(eject, "_safe_remove", return_value=True):
            result = eject.eject_disk(disk, on_stage=seen.append)
        self.assertTrue(result.success)
        self.assertEqual(seen, ["正在尝试：系统弹出…", "正在尝试：移除设备…"])

    def test_plain_mode_retries_until_success(self):
        """plain：第一次被拒、第二次成功，全程不改磁盘状态。"""
        disk = disk_query.DiskInfo(2, "X", 0, ("H",), True, pnp_id="PNP\\X")
        with mock.patch.object(eject, "shell_status", return_value={"H": "NOVERB"}), \
                mock.patch.object(eject, "letter_present", return_value=True), \
                mock.patch.object(eject, "wait_gone", return_value=[]), \
                mock.patch.object(eject, "SETTLE_BUDGET", 0.05), \
                mock.patch.object(eject, "_safe_remove", side_effect=[False, True]):
            result = eject.eject_disk(disk)
        self.assertTrue(result.success)
        self.assertEqual(result.stage, "pnp_remove")

    def test_plain_mode_failure_reports_holder(self):
        disk = disk_query.DiskInfo(2, "X", 0, ("H",), True, pnp_id="PNP\\X")
        with mock.patch.object(eject, "shell_status", return_value={"H": "NOVERB"}), \
                mock.patch.object(eject, "letter_present", return_value=True), \
                mock.patch.object(eject, "wait_gone", return_value=[]), \
                mock.patch.object(eject.pnp, "request_eject",
                                  return_value=(False, "设备本身拒绝移除")):
            result = eject.eject_disk(disk)
        self.assertFalse(result.success)
        self.assertEqual(result.stage, "device_veto")
        self.assertIn("拒绝安全移除", " ".join(result.details))

    def test_safe_remove_success_reports_pnp_stage(self):
        with mock.patch.object(eject.pnp, "request_eject", return_value=(True, "")):
            self.assertTrue(eject._safe_remove("PNP\\X", []))

    def test_safe_remove_veto_is_reported_not_forced(self):
        details = []
        with mock.patch.object(eject.pnp, "request_eject",
                               return_value=(False, "仍有文件或句柄处于打开状态：explorer.exe")):
            ok = eject._safe_remove("PNP\\X", details)
        self.assertFalse(ok)
        self.assertIn("explorer.exe", " ".join(details))

class DiskQueryHelpersTest(unittest.TestCase):
    def test_single_object_becomes_list(self):
        self.assertEqual(disk_query._as_list({"Index": 1}), [{"Index": 1}])
        self.assertEqual(disk_query._as_list(None), [])
        self.assertEqual(disk_query._as_list([{"a": 1}, "x"]), [{"a": 1}])

    def test_format_size(self):
        gib = 1024 ** 3
        self.assertEqual(disk_query.format_size(0), "—")
        self.assertEqual(disk_query.format_size(461 * gib), "461 GB")
        self.assertEqual(disk_query.format_size(int(931.5 * gib)), "931 GB")
        self.assertEqual(disk_query.format_size(int(99.5 * gib)), "99.5 GB")
        self.assertEqual(disk_query.format_size(2 * 1024 * gib), "2.00 TB")

    def test_external_classification_by_bus(self):
        external, reasons = disk_query._classify("SCSI", "FIXED HARD DISK MEDIA", "USBSTOR\\X", "USB", False)
        self.assertTrue(external)
        self.assertTrue(any("总线=USB" in reason for reason in reasons))

    def test_internal_disk_is_not_external(self):
        external, _ = disk_query._classify("SCSI", "FIXED HARD DISK MEDIA", "SCSI\\DISK", "NVME", False)
        self.assertFalse(external)

    def test_letters_text(self):
        disk = disk_query.DiskInfo(2, "Model X", 10, ("E", "F"), True)
        self.assertEqual(disk.letters_text, "E:、F:")
        self.assertEqual(disk.type_text, "外接")


class DiskQueryCollectionTest(unittest.TestCase):
    PAYLOAD = {
        "Disks": [
            {"Index": 0, "Model": "System SCSI", "Size": 1000, "InterfaceType": "SCSI",
             "MediaType": "Fixed hard disk media", "PNPDeviceID": "SCSI\\DISK&VEN"},
            {"Index": 2, "Model": "SanDisk", "Size": 2000, "InterfaceType": "USB",
             "MediaType": "Removable Media", "PNPDeviceID": "USBSTOR\\DISK&VEN"},
            {"Index": 4, "Model": "Card reader", "Size": None, "InterfaceType": "USB",
             "MediaType": "", "PNPDeviceID": "USB\\VID"},
        ],
        "Partitions": [{"DiskNumber": 0, "DriveLetter": "C"}, {"DiskNumber": 2, "DriveLetter": "E"}],
        "States": [{"Number": 0, "IsOffline": False, "BusType": "NVMe"},
                   {"Number": 2, "IsOffline": True, "BusType": "USB"},
                   {"Number": 4, "IsOffline": False, "BusType": "USB"}],
    }

    def test_only_external_disks_by_default(self):
        result = self._collect(show_all=False)
        self.assertEqual([disk.index for disk in result], [2])
        self.assertEqual(result[0].letters, ("E",))
        self.assertTrue(result[0].is_offline)

    def test_show_all_keeps_internal_but_skips_empty_media(self):
        result = self._collect(show_all=True)
        # 4 号读卡器没有容量也没有盘符：列出来只会让人误以为可以操作
        self.assertEqual([disk.index for disk in result], [0, 2])
        self.assertEqual(result[0].state_text, "联机")
        self.assertEqual(result[1].type_text, "外接")

    def _collect(self, show_all: bool):
        with mock.patch.object(disk_query, "_run_payload", return_value=self.PAYLOAD), \
                mock.patch.object(disk_query, "drive_type", return_value=3):
            return disk_query.query_disks(show_all=show_all)


class WinprocTest(unittest.TestCase):
    def test_timeout_kills_process_tree(self):
        # wraps=真实实现：既验证被调用，也真的把子进程杀掉（否则会留下 sleep 30 的进程）
        with mock.patch.object(winproc, "kill_tree", wraps=winproc.kill_tree) as killer:
            with self.assertRaises(winproc.CommandTimeout):
                winproc.run(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    timeout=0.6,
                )
        killer.assert_called_once()

    def test_nonzero_exit_is_reported(self):
        result = winproc.run([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10)
        self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()


class DiskSnapshotTest(unittest.TestCase):
    """启动快照：写—读要能还原同样的磁盘信息，坏文件必须当作"没有"。"""

    def setUp(self):
        import tempfile
        self._temp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self._temp.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp.cleanup()

    @staticmethod
    def _disk(index=2, letters=("H",), external=True):
        return disk_query.DiskInfo(
            index=index, model="Seagate Portable", size_bytes=2 * 1024 ** 4,
            letters=letters, is_external=external, pnp_id="USBSTOR\\DISK&VEN_X",
            interface="USB", media="EXTERNAL HARD DISK MEDIA", bus_type="USB",
            is_offline=False,
        )

    def test_roundtrip(self):
        disk = self._disk()
        disk_query.save_snapshot([disk])
        loaded = disk_query.load_snapshot()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].index, disk.index)
        self.assertEqual(loaded[0].model, disk.model)
        self.assertEqual(loaded[0].size_bytes, disk.size_bytes)
        self.assertEqual(loaded[0].letters, disk.letters)
        self.assertEqual(loaded[0].is_external, disk.is_external)
        self.assertEqual(loaded[0].pnp_id, disk.pnp_id)
        self.assertEqual(loaded[0].bus_type, disk.bus_type)
        self.assertEqual(loaded[0].is_offline, disk.is_offline)

    def test_garbage_is_ignored(self):
        path = disk_query.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(disk_query.load_snapshot(), [])

    def test_wrong_version_is_ignored(self):
        path = disk_query.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 99, "disks": []}), encoding="utf-8")
        self.assertEqual(disk_query.load_snapshot(), [])

    def test_seed_cache_makes_disk_findable(self):
        disk = self._disk(index=7)
        disk_query.clear_cache()
        disk_query.seed_cache([disk])
        self.assertIs(disk_query.find_disk_by_index(7), disk)
        disk_query.clear_cache()
        self.assertIsNone(disk_query.find_disk_by_index(7))


class WarningTriangleGeometryTest(unittest.TestCase):
    """警告三角的几何只有一处权威（tools/design_badges.py），对话框兜底必须与它一致。

    这类"两处画同一个图形"的代码最容易悄悄分叉：改了一边、另一边还是老形状，
    只有资源缺失走兜底时才暴露。判据是逐点相等 + 等边 + 包围盒居中。
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "design_badges", os.path.join(root, "tools", "design_badges.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.badges = module
        from gui import dialog as dialog_module
        cls.dialog = dialog_module

    def test_equilateral(self):
        for size in (43, 54, 75, 108):
            geometry = self.badges.warning_geometry(size)
            apex = geometry["apex"]
            left = geometry["left"]
            right = geometry["right"]
            base = right[0] - left[0]
            height = left[1] - apex[1]
            self.assertAlmostEqual(height / base, 3 ** 0.5 / 2, places=6)
            # 包围盒垂直居中
            self.assertAlmostEqual((apex[1] + left[1]) / 2.0, size / 2.0, places=6)

    def test_dialog_fallback_matches_generator(self):
        for size in (43, 54, 75, 108):
            a = self.badges.warning_geometry(size)
            b = self.dialog._warning_geometry(float(size))
            for key in ("apex", "left", "right"):
                self.assertAlmostEqual(a[key][0], b[key][0], places=6)
                self.assertAlmostEqual(a[key][1], b[key][1], places=6)
            self.assertAlmostEqual(a["centroid_y"], b["centroid_y"], places=6)
            self.assertAlmostEqual(a["stroke"], b["stroke"], places=6)
            self.assertEqual(len(a["inner"]), len(b["inner"]))
            for pa, pb in zip(a["inner"], b["inner"]):
                self.assertAlmostEqual(pa[0], pb[0], places=6)
                self.assertAlmostEqual(pa[1], pb[1], places=6)
