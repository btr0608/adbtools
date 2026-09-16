"""设备系统监控服务：合并一次 adb shell 获取磁盘/内存/温度三项指标。

替代原 StorageService 的 30s 轮询方案：
- 一次 adb shell 往返拿全三项，减少 adb 调用次数
- 2s 刷新频率（BSP 调试需要实时看温度变化）
- 后台 QThread 执行，信号槽回主线程
- 模拟器没有 thermal_zone 时自动隐藏温度条
"""
import re
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from ..core.adb_client import AdbClient
from ..core.utils import decode_bytes, get_startup_info, safe_is_running


# 合并 shell 命令：一次往返拿三项 + 探测 thermal 是否存在
# 用 grep -E 替代 head -1，同时捕获 MemTotal 和 MemAvailable
_MONITOR_CMD = (
    "grep -E 'MemTotal|MemAvailable' /proc/meminfo 2>/dev/null; "
    "ls /sys/class/thermal/ 2>/dev/null; "
    "df -Pk /sdcard 2>/dev/null | tail -1"
)

# 解析内存输出: MemTotal:       8192000 kB / MemAvailable:    4096000 kB
_MEM_TOTAL_RE = re.compile(r'MemTotal:\s+(\d+)\s+kB')
_MEM_AVAIL_RE = re.compile(r'MemAvailable:\s+(\d+)\s+kB')
# 解析温度原始值（整数，可能是毫度或度数）
_TEMP_RAW_RE = re.compile(r'(\d{2,8})')
# 解析 df 输出: /dev/block/...  1105123 762345 342778 69% /sdcard
_DF_RE = re.compile(r'\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+(\S+)$')


class SystemMonitorWorker(QThread):
    """单次后台采集三项指标。"""
    stats_done = pyqtSignal(
        bool, int, int, int,    # disk_ok, disk_pct, disk_used_kb, disk_total_kb
        int, int, int,            # mem_pct, mem_total_kb, mem_avail_kb
        bool, float               # temp_available, temp_c
    )

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled or not self.adb_client.serial:
            return

        # 默认值
        disk_ok = False
        disk_pct = disk_used_kb = disk_total_kb = 0
        mem_pct = mem_total_kb = mem_avail_kb = 0
        temp_available = False
        temp_c = 0.0

        try:
            import subprocess

            cmd = self.adb_client._build_cmd('shell', _MONITOR_CMD)
            raw = subprocess.check_output(
                cmd, stderr=subprocess.STDOUT, timeout=8,
                startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
            )
            text = decode_bytes(raw)
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            # 逐段解析：
            # 1. MemTotal / MemAvailable（可能 1-2 行，都以 Mem 开头）
            # 2. thermal_zone 列表（多行目录项，以 thermal_zone 开头或任何行但不含 Mem/df 关键字）
            # 3. df 输出（包含 % 和挂载点）
            mem_total_kb = 0
            mem_avail_kb = 0
            thermal_zone_found = False
            df_line = None

            for line in lines:
                if line.startswith('MemTotal:'):
                    m = _MEM_TOTAL_RE.search(line)
                    if m:
                        mem_total_kb = int(m.group(1))
                elif line.startswith('MemAvailable:'):
                    m = _MEM_AVAIL_RE.search(line)
                    if m:
                        mem_avail_kb = int(m.group(1))
                elif 'thermal_zone' in line:
                    thermal_zone_found = True
                elif '%' in line and '/' in line:
                    df_line = line

            # 计算内存百分比
            if mem_total_kb > 0 and mem_avail_kb > 0:
                mem_pct = int(max(0, min(100,
                    (mem_total_kb - mem_avail_kb) * 100 / mem_total_kb
                )))

            # 温度探测：只有 thermal_zone 目录存在才尝试读温度
            if thermal_zone_found:
                # 单独读一次 thermal_zone0/temp（模拟器可能存在目录但读不到有效数据）
                try:
                    temp_cmd = self.adb_client._build_cmd(
                        'shell', 'cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null'
                    )
                    temp_raw = subprocess.check_output(
                        temp_cmd, stderr=subprocess.STDOUT, timeout=3,
                        startupinfo=get_startup_info(), cwd=self.adb_client.adb_home,
                    )
                    temp_text = decode_bytes(temp_raw).strip()
                    if temp_text:
                        m = _TEMP_RAW_RE.search(temp_text)
                        if m:
                            raw_temp = int(m.group(1))
                            # 判断是毫度（>1000 通常是）还是度数
                            if raw_temp > 1000:
                                temp_c = raw_temp / 1000.0
                            else:
                                temp_c = float(raw_temp)
                            # 合理性检查：20℃~120℃ 才认为有效
                            if 20.0 <= temp_c <= 120.0:
                                temp_available = True
                except Exception:
                    pass

            # 解析 df
            if df_line:
                m = _DF_RE.search(df_line)
                if m:
                    disk_total_kb = int(m.group(1))
                    disk_used_kb = int(m.group(2))
                    disk_pct = int(m.group(4))
                    disk_ok = disk_total_kb > 0

        except Exception:
            pass

        if not self._cancelled:
            self.stats_done.emit(
                disk_ok, disk_pct, disk_used_kb, disk_total_kb,
                mem_pct, mem_total_kb, mem_avail_kb,
                temp_available, temp_c,
            )


class SystemMonitorService(QObject):
    """统一系统监控：2s 轮询一次，单次 adb shell 拿磁盘+内存+温度。"""

    stats_updated = pyqtSignal(
        bool, int, int, int,    # disk_ok, disk_pct, disk_used_kb, disk_total_kb
        int, int, int,            # mem_pct, mem_total_kb, mem_avail_kb
        bool, float               # temp_available, temp_c
    )

    def __init__(self, adb_client: AdbClient):
        super().__init__()
        self.adb_client = adb_client
        self._worker: Optional[SystemMonitorWorker] = None

    def refresh(self):
        """立即触发一次采集；旧查询未完成时取消后重发。"""
        if not self.adb_client.serial:
            return

        if safe_is_running(self._worker):
            self._worker.cancel()
            try:
                self._worker.stats_done.disconnect()
            except (TypeError, RuntimeError):
                pass
        self._worker = None

        self._worker = SystemMonitorWorker(self.adb_client)
        self._worker.stats_done.connect(self.stats_updated)
        from ..core.utils import start_worker
        start_worker(self._worker)
