"""多策略弹出。

顺序：Shell 弹出 → 按 0.4 s 间隔重试 PnP 移除（不改磁盘状态）。

性能上的关键事实（2026-10-22 实测）：

* PowerShell 进程启动 ~0.2 s，单次 CIM 查询 ~0.3 s——**不是**主要成本；
* 真正的成本是原实现每阶段后面**盲等 3 秒**，以及给没有 "弹出" 动词的
  设备（USB-SATA 桥基本都是）先调一遍 Shell；
* 实测那块 1.82 TB 移动硬盘：Shell 查动词返回 ``NO_EJECT``，整条链 11 s。

所以这里：

* Shell 阶段先查动词，**没有动词就不调用、不等待**；
* 等待从 3.0 s 降到 1.5 s，轮询 100 ms；没调用到的盘符一秒都不等；
* 每个阶段只起一次 PowerShell（多盘符合并），不再按盘符各起一次；
* PnP 存在性用 ``CM_Locate_DevNodeW``（毫秒级），失败才退回 PowerShell；
* 阶段变化通过 ``on_stage`` 回调抛给界面，状态栏能看到"正在尝试哪一步"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import disk_attr, disk_query, pnp, winproc
from .i18n import L

#: 等待盘符消失的上限（秒）
LETTER_WAIT = 1.5
#: 轮询间隔（秒）
POLL_INTERVAL = 0.1
#: 解除占用后等待卷落定的总预算（秒）
SETTLE_BUDGET = 10.0

#: 已知没有 Shell "弹出"动词的设备（PNPDeviceID），下次直接跳过 0.7 s 的查询
_SHELL_NOVERB: set = set()

#: 阶段回调：界面用它更新状态栏
StageCallback = Callable[[str], None]

_SHELL_SCRIPT = r"""
$ns=(New-Object -ComObject Shell.Application).NameSpace(17)
$out=@()
foreach($l in @(__LETTERS__)){
  $item=$ns.ParseName("${l}:")
  if($item -eq $null){ $out += "${l}:NOITEM"; continue }
  $verb=@($item.Verbs() | Where-Object { $_.Name -match 'Eject|弹出' }) | Select-Object -First 1
  if($verb -eq $null){ $out += "${l}:NOVERB"; continue }
  $item.InvokeVerb('Eject')
  $out += "${l}:INVOKED"
}
$out
"""




@dataclass
class EjectResult:
    success: bool
    stage: str
    details: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"success": self.success, "stage": self.stage, "details": self.details}


def letter_present(letter: str) -> bool:
    """盘符是否还存在（``GetDriveTypeW`` 返回 0/1 视为不存在）。"""
    return disk_query.drive_type(letter) > 1


def _clean_letters(letters: List[str]) -> List[str]:
    cleaned = []
    for letter in letters:
        value = str(letter).strip(":\\").upper()[:1]
        if value.isalpha() and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _letters_literal(letters: List[str]) -> str:
    return ",".join(f"'{letter}'" for letter in letters)


def parse_statuses(lines: List[str]) -> Dict[str, str]:
    """把 ``E:INVOKED`` 这类行解析成 ``{'E': 'INVOKED'}``。"""
    statuses: Dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        letter, _, value = line.partition(":")
        letter = letter.strip().upper()[:1]
        if letter.isalpha():
            statuses[letter] = value.strip()
    return statuses


def _ps_lines(script: str) -> List[str]:
    result = winproc.run_powershell(script, timeout=20)
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def shell_status(letters: List[str]) -> Dict[str, str]:
    """查每个盘符有没有"弹出"动词，有才调用。返回 ``{letter: INVOKED|NOVERB|NOITEM}``。"""
    cleaned = _clean_letters(letters)
    if not cleaned:
        return {}
    try:
        lines = _ps_lines(_SHELL_SCRIPT.replace("__LETTERS__", _letters_literal(cleaned)))
    except winproc.CommandError:
        return {}
    return parse_statuses(lines)


def wait_gone(letters: List[str], timeout: float = LETTER_WAIT) -> List[str]:
    """等这些盘符消失，返回真正消失的那些（到时间没消失的不返回）。"""
    pending = set(letters)
    gone: List[str] = []
    deadline = time.monotonic() + timeout
    while pending:
        for letter in list(pending):
            if not letter_present(letter):
                gone.append(letter)
                pending.discard(letter)
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL)
    return gone


def _safe_remove(pnp_id: str, details: List[str]) -> bool:
    """用系统自己的"安全移除"接口请求弹出（不是强制删设备节点）。

    这是资源管理器"安全删除硬件"用的同一个接口：会先让驱动卸载卷、再移除设备。
    有程序占用时返回 veto 原因（含占用者名字），**不会硬删**，盘符也不会被弄丢。
    """
    if not pnp_id:
        details.append(L("没有取得 PNPDeviceID，跳过安全移除",
                             "No PNPDeviceID, skipping safe removal"))
        return False
    ok, message = pnp.request_eject(pnp_id)
    if ok:
        details.append(L(f"系统已安全移除设备 => {pnp_id}",
                             f"Device safely removed => {pnp_id}"))
        if message:
            details.append(message)
        return True
    details.append(L(f"系统拒绝安全移除：{message}",
                             f"System refused safe removal: {message}"))
    return False


def eject_disk(disk: disk_query.DiskInfo,
               on_stage: Optional[StageCallback] = None) -> EjectResult:
    """一键弹出：Shell 动词 → 按 0.4 s 间隔礼貌重试系统移除。

    设计原则（2026-10-24 实测定稿）：**不为了快而去改磁盘状态**。
    脱机 / 强制卸载 / 脱机→联机都试过，全部更慢（16.9 s、10 次否决），
    而且会把盘留成脱机、重插读不到。现在只做两件事：

    * 有 Shell "弹出"动词就先试（部分 U 盘可以直接成功）；
    * 没有就按 0.4 s 间隔请求系统移除，最多 SETTLE_BUDGET 秒——Windows 自己会在
      几秒内放开卷（实测 2~4 次否决后成功），全程不动磁盘状态。
    """
    details: List[str] = []
    letters = _clean_letters(list(disk.letters))
    for letter in letters:
        lockable = disk_attr.volume_lockable(letter)
        if lockable is None:
            details.append(L(f"卷状态 {letter}: 无法查询", f"Volume {letter}: cannot query state"))
        else:
            details.append(L(f"卷状态 {letter}: "
                             + ("可锁定（无打开句柄）" if lockable else "被占用（有打开句柄）"),
                             f"Volume {letter}: "
                             + ("lockable (no open handles)" if lockable else "in use (open handles)")))

    def stage(text: str) -> None:
        if on_stage is not None:
            try:
                on_stage(text)
            except Exception:  # pragma: no cover - 回调不该影响流程
                pass

    if not letters:
        details.append(L("该磁盘没有盘符，跳过 Shell 弹出",
                             "Disk has no drive letter, skipping Shell eject"))
    elif disk.pnp_id and disk.pnp_id in _SHELL_NOVERB:
        details.append(L("Shell 弹出跳过：该设备上次没有“弹出”动词，本次直接跳过",
                             "Shell eject skipped: this device had no eject verb last time"))
    else:
        stage(L("正在尝试：系统弹出…", "Trying: system eject…"))
        started = time.perf_counter()
        statuses = shell_status(letters)
        invoked: List[str] = []
        for letter in letters:
            state = statuses.get(letter, "UNKNOWN")
            if state == "INVOKED":
                invoked.append(letter)
                details.append(L(f"Shell 弹出已调用：{letter}:", f"Shell eject invoked: {letter}:"))
            elif state == "NOVERB":
                details.append(L(f"Shell 弹出跳过：{letter}: 没有“弹出”动词",
                                 f"Shell eject skipped: {letter}: no eject verb"))
            elif state == "NOITEM":
                details.append(L(f"Shell 弹出跳过：{letter}: 卷不存在",
                                 f"Shell eject skipped: {letter}: volume missing"))
            else:
                details.append(L(f"Shell 弹出未执行：{letter}:（查询失败，继续下一策略）",
                                 f"Shell eject not run: {letter}: (query failed, trying next)  "))
        gone = wait_gone(invoked)
        for letter in gone:
            details.append(L(f"Shell 弹出成功：{letter}:", f"Shell eject succeeded: {letter}:"))
        details.append(L(f"系统弹出阶段用时 {time.perf_counter() - started:.2f} s",
                         f"Shell eject stage took {time.perf_counter() - started:.2f} s"))
        if gone:
            return EjectResult(True, "shell_com", details)
        if disk.pnp_id and statuses and not invoked \
                and all(state in ("NOVERB", "NOITEM") for state in statuses.values()):
            # 记住"这个设备没有弹出动词"，下次直接省掉 0.7 s 的查询
            _SHELL_NOVERB.add(disk.pnp_id)

    stage(L("正在尝试：移除设备…", "Trying: remove device…"))
    started = time.perf_counter()
    deadline = time.monotonic() + SETTLE_BUDGET
    while True:
        if _safe_remove(disk.pnp_id, details):
            details.append(L(f"移除设备阶段用时 {time.perf_counter() - started:.2f} s",
                         f"Device removal stage took {time.perf_counter() - started:.2f} s"))
            return EjectResult(True, "pnp_remove", details)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    details.append(L(f"移除设备阶段用时 {time.perf_counter() - started:.2f} s",
                     f"Device removal stage took {time.perf_counter() - started:.2f} s"))
    details.append(L("设备保持原状，可以稍后重试。",
                     "Device left untouched; try again later."))
    return EjectResult(False, "device_veto", details)


def stage_hint(stage: str) -> str:
    """把阶段名翻译成用户能看懂的一句话。"""
    return {
        "shell_com": L("系统已弹出该设备，可以拔下。",
                       "The system ejected the device; it can be unplugged."),
        "pnp_remove": L("系统已安全移除设备，盘符已释放，可以拔下。",
                        "The device was safely removed and the drive letter released; "
                        "it can be unplugged."),
        "device_veto": L("设备仍在使用中（通常是资源管理器还开着该盘，或 Windows 搜索正在索引）。"
                         "已保持原状；等几秒再点一次「弹出」通常就能成功，或关掉该盘的资源管理器窗口。"
                         "若资源管理器里看不到盘符，重新插拔一次即可恢复。",
                         "The device is still in use (usually Explorer has the drive open, or "
                         "Windows Search is indexing it). It was left untouched; waiting a few "
                         "seconds and ejecting again usually works, or close that Explorer window. "
                         "If the drive letter disappears from Explorer, re-plug once to recover."),
    }.get(stage, "")
