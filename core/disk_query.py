"""磁盘枚举。

与原实现的区别（都是为了少等几秒、少出几个空列表）：

* **一次 PowerShell 调用取回全部数据**（磁盘 + 分区 + 状态），原实现是三次
  （`Win32_DiskDrive` / `Get-Partition` / `Win32_LogicalDisk`），每次
  起一个 PowerShell 进程约 0.5~1 秒；
* **驱动器类型用 ``GetDriveTypeW``**（毫秒级），不再为 ``DriveType=2``
  单独跑一次 PowerShell；
* PowerShell 失败不再**静默返回空列表**——空列表在界面上等于"没有磁盘"，
  必须让调用方区分"确实没有设备"和"查询失败"；
* ``Get-Partition`` 失败时才走逐磁盘关联的降级路径，且降级也只用一次
  调用（原实现是每个磁盘一次）。
"""

from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import applog, i18n, winproc
from .i18n import L

DEBUG = bool(os.environ.get("QFE_DEBUG"))

DRIVE_REMOVABLE = 2

#: 一次查询最多等 25 秒（冷启动的 PowerShell + 慢速 CIM 也够用）
QUERY_TIMEOUT = 25.0

_EXTERNAL_BUS = {"USB", "SD", "MMC"}


class DiskQueryError(RuntimeError):
    """磁盘查询失败（与"没有可移动磁盘"区分开）。"""


@dataclass(frozen=True)
class DiskInfo:
    index: int
    model: str
    size_bytes: int
    letters: Tuple[str, ...]
    is_external: bool
    pnp_id: str = ""
    interface: str = ""
    media: str = ""
    bus_type: str = ""
    is_offline: Optional[bool] = None

    @property
    def size_text(self) -> str:
        return format_size(self.size_bytes)

    @property
    def letters_text(self) -> str:
        separator = "、" if i18n.language() == "zh" else ", "
        return separator.join(f"{letter}:" for letter in self.letters) or "—"

    @property
    def type_text(self) -> str:
        return L("外接", "External") if self.is_external else L("内置", "Internal")

    @property
    def state_text(self) -> str:
        if self.is_offline is None:
            return "—"
        return L("脱机", "Offline") if self.is_offline else L("联机", "Online")


def format_size(size_bytes: int) -> str:
    """按 Windows 资源管理器的口径显示容量（1 GB = 1024³ 字节）。"""
    if not size_bytes or size_bytes <= 0:
        return "—"
    gb = size_bytes / (1024 ** 3)
    if gb >= 1000:
        return f"{gb / 1024:.2f} TB"
    if gb >= 100:
        # 与资源管理器一致：三位数容量取整（向下），931.5 GiB 显示 931 GB
        return f"{int(gb)} GB"
    return f"{gb:.1f} GB"


def drive_type(letter: str) -> int:
    """``GetDriveTypeW``：不给不存在的盘符起进程。"""
    letter = (letter or "").strip(":\\").upper()[:1]
    if not letter or not letter.isalpha():
        return 0
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\"))
    except Exception:
        return 0


def _as_list(value: Any) -> List[Dict[str, Any]]:
    """PowerShell 的单元素数组会被序列化成对象，这里统一成列表。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


_DISK_SCRIPT = (
    "$disks=@(Get-CimInstance Win32_DiskDrive | ForEach-Object {"
    "[pscustomobject]@{Index=$_.Index;Model=$_.Model;Size=$_.Size;"
    "InterfaceType=$_.InterfaceType;MediaType=$_.MediaType;PNPDeviceID=$_.PNPDeviceID}});"
    "$parts=@();"
    "try{$parts=@(Get-Partition -ErrorAction Stop | Where-Object {$_.DriveLetter} | "
    "ForEach-Object {[pscustomobject]@{DiskNumber=$_.DiskNumber;DriveLetter=[string]$_.DriveLetter}})}catch{};"
    "$states=@();"
    "try{$states=@(Get-Disk -ErrorAction Stop | ForEach-Object {"
    "[pscustomobject]@{Number=$_.Number;IsOffline=[bool]$_.IsOffline;BusType=[string]$_.BusType}})}catch{};"
    "[pscustomobject]@{Disks=$disks;Partitions=$parts;States=$states} | "
    "ConvertTo-Json -Depth 5 -Compress"
)

_FALLBACK_SCRIPT = (
    "$map=@{};"
    "foreach($d in (Get-CimInstance Win32_DiskDrive)){"
    "$letters=@();"
    "foreach($p in ($d | Get-CimAssociatedInstance -Association Win32_DiskDriveToDiskPartition)){"
    "foreach($l in ($p | Get-CimAssociatedInstance -Association Win32_LogicalDiskToPartition)){"
    "if($l.DeviceID){$letters+=$l.DeviceID.Substring(0,1)}}};"
    "$map[[string]$d.Index]=$letters};"
    "$map | ConvertTo-Json -Compress"
)


def _run_payload(script: str, timeout: float) -> Any:
    result = winproc.run_powershell(script, timeout=timeout)
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiskQueryError(L(f"PowerShell 返回的内容不是 JSON：{raw[:200]}",
                               f"PowerShell output is not JSON: {raw[:200]}")) from exc


def _fallback_letters(timeout: float) -> Dict[int, List[str]]:
    """``Get-Partition`` 不可用（旧系统）时按 CIM 关联补盘符。"""
    try:
        mapping = _run_payload(_FALLBACK_SCRIPT, timeout)
    except (winproc.CommandError, DiskQueryError) as exc:
        _debug(f"降级查询盘符失败：{exc}")
        return {}
    result: Dict[int, List[str]] = {}
    if not isinstance(mapping, dict):
        return result
    for key, value in mapping.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str):
            values: Iterable[Any] = [value]
        elif isinstance(value, list):
            values = value
        else:
            values = []
        letters = []
        for item in values:
            letter = str(item).strip(":\\").upper()[:1]
            if letter.isalpha():
                letters.append(letter)
        if letters:
            result[index] = sorted(set(letters))
    return result


def _debug(message: str) -> None:
    if DEBUG:
        applog.write("debug", message)


def _collect(timeout: float) -> List[DiskInfo]:
    payload = _run_payload(_DISK_SCRIPT, timeout)
    if not isinstance(payload, dict):
        raise DiskQueryError(L("PowerShell 没有返回磁盘数据", "PowerShell returned no disk data"))

    disks = _as_list(payload.get("Disks"))
    partitions = _as_list(payload.get("Partitions"))
    states = _as_list(payload.get("States"))

    letters_by_disk: Dict[int, List[str]] = {}
    for part in partitions:
        number = part.get("DiskNumber")
        letter = str(part.get("DriveLetter") or "").strip(":\\").upper()[:1]
        if number is None or not letter:
            continue
        try:
            letters_by_disk.setdefault(int(number), []).append(letter)
        except (TypeError, ValueError):
            continue

    if disks and not letters_by_disk:
        _debug("Get-Partition 没有返回盘符，改走 CIM 关联降级查询")
        letters_by_disk = _fallback_letters(timeout)

    offline_by_disk: Dict[int, bool] = {}
    bus_by_disk: Dict[int, str] = {}
    for state in states:
        number = state.get("Number")
        try:
            index = int(number)
        except (TypeError, ValueError):
            continue
        offline_by_disk[index] = bool(state.get("IsOffline"))
        bus_by_disk[index] = str(state.get("BusType") or "").upper()

    _orphans = _find_orphan_letters(letters_by_disk) if partitions or letters_by_disk else []
    if _orphans:
        _debug(f"检测到没有对应磁盘的盘符：{_orphans}")
    global _orphan_letters
    _orphan_letters = _orphans

    result: List[DiskInfo] = []
    for raw_disk in disks:
        try:
            index = int(raw_disk.get("Index"))
        except (TypeError, ValueError):
            continue
        try:
            size = int(raw_disk.get("Size") or 0)
        except (TypeError, ValueError):
            size = 0        # 单条数据畸形只影响这台磁盘，不能让整次查询失败
        letters = tuple(sorted(set(letters_by_disk.get(index, []))))
        interface = str(raw_disk.get("InterfaceType") or "").upper()
        media = str(raw_disk.get("MediaType") or "").upper()
        pnp_id = str(raw_disk.get("PNPDeviceID") or "")
        bus_type = bus_by_disk.get(index, "")
        removable_letter = any(drive_type(letter) == DRIVE_REMOVABLE for letter in letters)
        external, reasons = _classify(interface, media, pnp_id, bus_type, removable_letter)
        _debug(
            f"disk {index}: model={raw_disk.get('Model')!r} size={size} letters={letters} "
            f"interface={interface} media={media} bus={bus_type} pnp_usb={'USB' in pnp_id.upper()} "
            f"removable_letter={removable_letter} -> external={external} ({', '.join(reasons) or '无信号'})"
        )
        if size <= 0 and not letters:
            # 读卡器空槽/无介质：既没容量也没有盘符，列出来只会让人误会
            _debug(f"disk {index}: 无介质，跳过")
            continue
        result.append(
            DiskInfo(
                index=index,
                model=str(raw_disk.get("Model") or "").strip(),
                size_bytes=size,
                letters=letters,
                is_external=external,
                pnp_id=pnp_id,
                interface=interface,
                media=media,
                bus_type=bus_type,
                is_offline=offline_by_disk.get(index),
            )
        )
    result.sort(key=lambda disk: disk.index)
    return result


def _classify(interface: str, media: str, pnp_id: str,
              bus_type: str, removable_letter: bool) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if "USB" in interface:
        reasons.append("接口=USB")
    if "EXTERNAL" in media or "REMOVABLE" in media:
        reasons.append("介质=可移动/外接")
    if removable_letter:
        reasons.append("卷类型=可移动")
    if "USBSTOR" in pnp_id.upper() or "USB" in pnp_id.upper():
        reasons.append("PNP=USB")
    if bus_type in _EXTERNAL_BUS:
        reasons.append(f"总线={bus_type}")
    return bool(reasons), reasons


_cache: List[DiskInfo] = []
_cache_valid = False
#: 有盘符、但没有任何磁盘对象对应的卷（设备被移除后 Windows 没清理干净）
_orphan_letters: List[str] = []


def _find_orphan_letters(letters_by_disk: Dict[int, List[str]]) -> List[str]:
    """找出"有盘符却没有对应磁盘"的卷。

    实测场景：``pnputil /remove-device`` 返回 3010（需要重启）后，磁盘对象
    从 ``Win32_DiskDrive`` 消失，但卷还挂在系统里——资源管理器看得到盘符，
    本工具却"没有磁盘"。把这类盘符单独提示出来，比显示"没有可移动磁盘"
    诚实得多。
    """
    mapped = {letter for letters in letters_by_disk.values() for letter in letters}
    try:
        mask = int(ctypes.windll.kernel32.GetLogicalDrives())
    except Exception:  # pragma: no cover - 非 Windows
        return []
    orphans: List[str] = []
    for offset in range(26):
        if not (mask >> offset) & 1:
            continue
        letter = chr(ord("A") + offset)
        if letter in mapped:
            continue
        if drive_type(letter) in (2, 3):  # 可移动 / 固定；排除光驱、网络盘
            orphans.append(letter)
    return orphans


def orphan_letters() -> List[str]:
    """上一次查询里"有盘符没有磁盘对象"的盘符（通常是设备已移除、卷未清理）。"""
    return list(_orphan_letters)


def query_disks(*, show_all: bool = False, timeout: float = QUERY_TIMEOUT) -> List[DiskInfo]:
    """枚举磁盘。只返回可移动磁盘，除非 ``show_all=True``。"""
    global _cache, _cache_valid
    disks = _collect(timeout)
    _cache = disks
    _cache_valid = True
    if show_all:
        return list(disks)
    return [disk for disk in disks if disk.is_external]


def find_disk_by_index(index: int) -> Optional[DiskInfo]:
    for disk in _cache:
        if disk.index == index:
            return disk
    return None


def cached_disks() -> List[DiskInfo]:
    return list(_cache)


def has_cache() -> bool:
    return _cache_valid


def clear_cache() -> None:
    global _cache, _cache_valid, _orphan_letters
    _cache = []
    _cache_valid = False
    _orphan_letters = []


# --------------------------------------------------------------------------- #
# 上次查询的快照：启动时先把列表画出来，再在后台真查一遍
#
# 实测（2026-10-24）：一次查询 1.2~1.4 s，开机后第一次要 4.3 s（PowerShell 冷启动 +
# CIM 模块加载）。窗口本身 0.8 s 就出来了，用户却要对着空列表等 1.5~4.5 s。
# 把上一次的结果存成快照，启动时先画出来，查询完成后再替换——等待时间从
# 1.5~4.5 s 降到 ~0.05 s（读快照）。刷新期间按钮全部禁用，所以不会对旧数据误操作。
# --------------------------------------------------------------------------- #

SNAPSHOT_NAME = "last-disks.json"
SNAPSHOT_VERSION = 1


def snapshot_path():
    return applog.log_dir() / SNAPSHOT_NAME


def save_snapshot(disks: List[DiskInfo]) -> None:
    """把整份磁盘列表写成快照（原子替换；失败静默）。"""
    payload = {
        "version": SNAPSHOT_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "disks": [
            {
                "index": disk.index,
                "model": disk.model,
                "size": disk.size_bytes,
                "letters": list(disk.letters),
                "external": disk.is_external,
                "pnp_id": disk.pnp_id,
                "interface": disk.interface,
                "media": disk.media,
                "bus": disk.bus_type,
                "offline": disk.is_offline,
            }
            for disk in disks
        ],
    }
    path = snapshot_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
        pass


def load_snapshot() -> List[DiskInfo]:
    """读回上次的快照；坏了/版本不对就当没有。"""
    try:
        with open(snapshot_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
        return []
    result: List[DiskInfo] = []
    for raw in payload.get("disks") or []:
        try:
            letters = tuple(str(letter).upper()[:1] for letter in raw.get("letters") or ())
            result.append(DiskInfo(
                index=int(raw["index"]),
                model=str(raw.get("model") or ""),
                size_bytes=int(raw.get("size") or 0),
                letters=letters,
                is_external=bool(raw.get("external")),
                pnp_id=str(raw.get("pnp_id") or ""),
                interface=str(raw.get("interface") or ""),
                media=str(raw.get("media") or ""),
                bus_type=str(raw.get("bus") or ""),
                is_offline=raw.get("offline") if isinstance(raw.get("offline"), bool) else None,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def seed_cache(disks: List[DiskInfo]) -> None:
    """把快照塞进内存缓存，好让 ``find_disk_by_index`` 在首查完成前也能查到。"""
    global _cache, _cache_valid
    _cache = list(disks)
    _cache_valid = True
