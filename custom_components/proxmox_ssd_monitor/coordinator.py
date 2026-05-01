"""DataUpdateCoordinator für Proxmox SSD Monitor."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_PORT, DEFAULT_USERNAME, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

CONF_KEY_HOST = "host"


class ProxmoxSSDCoordinator(DataUpdateCoordinator):
    """Koordiniert SSH-Abfragen zum Proxmox-Host alle N Minuten.

    coordinator.data hat folgende Struktur:
      {
        "disks": { disk_name: { ... SMART-Felder ... }, ... },
        "host":  { cpu_percent, ram_percent, temperatures, storages, ... },
      }
    """

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._entry = entry
        interval = entry.data.get(
            DOMAIN + "_scan_interval",
            entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    # ── SSH-Hilfsmethoden ─────────────────────────────────────────────────────

    def _make_client(self):
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self._entry.data[CONF_KEY_HOST],
            port=int(self._entry.data.get("port", DEFAULT_PORT)),
            username=self._entry.data.get("username", DEFAULT_USERNAME),
            password=self._entry.data.get("password", ""),
            timeout=15,
            banner_timeout=15,
        )
        return client

    @staticmethod
    def _run(client, cmd: str, timeout: int = 30) -> str:
        _, stdout, _ = client.exec_command(cmd, timeout=timeout)
        return stdout.read().decode("utf-8", errors="replace")

    # ── Haupt-Fetch ───────────────────────────────────────────────────────────

    def _fetch(self) -> dict:
        """Holt alle Daten (SMART + Host-Metriken) – läuft im Thread-Pool."""
        client = self._make_client()
        try:
            disks = self._fetch_disks(client)
            host  = self._fetch_host(client)
        finally:
            client.close()

        return {"disks": disks, "host": host}

    # ── Festplatten / SMART ───────────────────────────────────────────────────

    def _fetch_disks(self, client) -> dict:
        raw = self._run(client, "lsblk -o NAME,TYPE -J 2>/dev/null")
        disk_names: list[str] = []
        try:
            for dev in json.loads(raw).get("blockdevices", []):
                if dev.get("type") == "disk":
                    disk_names.append(dev["name"])
        except (json.JSONDecodeError, KeyError):
            _LOGGER.warning("lsblk-Ausgabe konnte nicht geparst werden")

        result: dict = {}
        for disk in disk_names:
            raw_smart = self._run(
                client,
                f"smartctl -a -j /dev/{disk} 2>/dev/null || "
                f"smartctl -a --tolerance=verypermissive -j /dev/{disk} 2>/dev/null",
            )
            try:
                result[disk] = _parse_smart(disk, json.loads(raw_smart))
            except Exception as exc:
                _LOGGER.debug("SMART-Parsing für %s fehlgeschlagen: %s", disk, exc)

        return result

    # ── Host-Metriken ─────────────────────────────────────────────────────────

    def _fetch_host(self, client) -> dict:
        # ── Kombinierter SSH-Aufruf ────────────────────────────────────────
        combined = (
            "echo '===STAT==='; cat /proc/stat | head -1; "
            "echo '===MEM==='; cat /proc/meminfo; "
            "echo '===UPTIME==='; cat /proc/uptime; "
            "echo '===LOAD==='; cat /proc/loadavg; "
            "echo '===TEMP==='; "
            "for f in /sys/class/thermal/thermal_zone*/temp; do "
            "  t=$(cat $f 2>/dev/null); "
            "  n=$(cat ${f%temp}type 2>/dev/null); "
            "  echo \"$n $t\"; "
            "done; "
            "echo '===CPU==='; "
            "grep -m1 'model name' /proc/cpuinfo 2>/dev/null; "
            "grep -m1 'cpu cores'  /proc/cpuinfo 2>/dev/null; "
            "echo '===SYSINFO==='; "
            "uname -r 2>/dev/null; "
            "pveversion 2>/dev/null | grep -m1 pve-manager; "
            "echo '===GUESTS==='; "
            "qm list 2>/dev/null | grep -c ' running ' || echo 0; "
            "pct list 2>/dev/null | grep -c ' running ' || echo 0"
        )
        out = self._run(client, combined, timeout=20)

        # ── Sections parsen ───────────────────────────────────────────────
        sections: dict[str, list[str]] = {}
        current = ""
        for line in out.splitlines():
            if line.startswith("===") and line.endswith("==="):
                current = line.strip("=")
            elif current:
                sections.setdefault(current, []).append(line)

        # ── RAM ───────────────────────────────────────────────────────────
        mem: dict[str, int] = {}
        for line in sections.get("MEM", []):
            if ":" in line:
                k, v = line.split(":", 1)
                try:
                    mem[k.strip()] = int(v.strip().split()[0])
                except (ValueError, IndexError):
                    pass

        ram_total_kb = mem.get("MemTotal", 0)
        ram_avail_kb = mem.get("MemAvailable", 0)
        ram_total    = ram_total_kb * 1024
        ram_avail    = ram_avail_kb * 1024
        ram_used     = ram_total - ram_avail
        ram_percent  = round(ram_used / ram_total * 100, 1) if ram_total else None
        ram_total_mb = round(ram_total / 1024 / 1024) if ram_total else None
        ram_used_mb  = round(ram_used  / 1024 / 1024) if ram_used  else None

        # ── Uptime ────────────────────────────────────────────────────────
        uptime_sec = None
        parts = (sections.get("UPTIME") or [""])[0].split()
        if parts:
            try:
                uptime_sec = int(float(parts[0]))
            except ValueError:
                pass

        # ── Load Average ─────────────────────────────────────────────────
        load_avg: list = []
        lp = (sections.get("LOAD") or [""])[0].split()
        if len(lp) >= 3:
            try:
                load_avg = [round(float(lp[i]), 2) for i in range(3)]
            except ValueError:
                pass

        # ── Temperaturen ─────────────────────────────────────────────────
        temps: dict = {}
        for line in sections.get("TEMP", []):
            p = line.split()
            if len(p) == 2:
                name, val = p
                try:
                    t = round(int(val) / 1000, 1)
                    if 0 < t < 150:
                        k = name
                        idx = 1
                        while k in temps:
                            k = f"{name}_{idx}"
                            idx += 1
                        temps[k] = t
                except ValueError:
                    pass

        # ── Sysinfo ───────────────────────────────────────────────────────
        si = sections.get("SYSINFO", [])
        kernel_version = si[0].strip() if si else None
        pve_version = None
        if len(si) > 1:
            raw_pve = si[1].strip()
            if "/" in raw_pve:
                pve_version = raw_pve.split("/")[1]
            elif raw_pve:
                pve_version = raw_pve

        # ── Guests ────────────────────────────────────────────────────────
        gl = sections.get("GUESTS", [])
        try:
            vm_count = int(gl[0].strip()) if gl else 0
        except (ValueError, IndexError):
            vm_count = 0
        try:
            ct_count = int(gl[1].strip()) if len(gl) > 1 else 0
        except (ValueError, IndexError):
            ct_count = 0

        # ── CPU-Info ─────────────────────────────────────────────────────
        cpu_model = None
        cpu_cores = None
        for line in sections.get("CPU", []):
            if "model name" in line and cpu_model is None:
                cpu_model = line.split(":", 1)[1].strip()
            elif "cpu cores" in line and cpu_cores is None:
                try:
                    cpu_cores = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

        # ── Proxmox-API: Status, Backup, Storage, Updates ────────────────
        uptime_pve = None
        last_backup_ts = None
        storages: list = []
        update_count = 0
        update_packages: list = []

        try:
            pv_raw = self._run(
                client,
                "pvesh get /nodes/localhost/status --output-format json 2>/dev/null",
                timeout=8,
            )
            if pv_raw.strip():
                pv = json.loads(pv_raw)
                uptime_pve = pv.get("uptime")
                if not cpu_model:
                    cpu_model = (pv.get("cpuinfo") or {}).get("model", "")
                if not cpu_cores:
                    cpu_cores = (pv.get("cpuinfo") or {}).get("cpus")
        except Exception:
            pass

        try:
            bk_raw = self._run(
                client,
                "pvesh get /nodes/localhost/tasks --limit 10 --typefilter vzdump"
                " --output-format json 2>/dev/null",
                timeout=8,
            )
            if bk_raw.strip():
                tasks = json.loads(bk_raw)
                if tasks:
                    last_backup_ts = tasks[0].get("starttime")
        except Exception:
            pass

        try:
            st_raw = self._run(
                client,
                "pvesh get /nodes/localhost/storage --output-format json 2>/dev/null",
                timeout=8,
            )
            if st_raw.strip():
                for s in json.loads(st_raw):
                    if not s.get("active") or not s.get("enabled"):
                        continue
                    total = s.get("total", 0)
                    used  = s.get("used",  0)
                    avail = s.get("avail", 0)
                    if not total:
                        continue
                    storages.append({
                        "name":     s.get("storage", "?"),
                        "type":     s.get("type", "?"),
                        "total_gb": round(total / 1e9, 1),
                        "used_gb":  round(used  / 1e9, 1),
                        "avail_gb": round(avail / 1e9, 1),
                        "pct":      round(used / total * 100, 1),
                    })
        except Exception:
            pass

        try:
            up_raw = self._run(
                client,
                "pvesh get /nodes/localhost/apt/updates --output-format json 2>/dev/null",
                timeout=12,
            )
            if up_raw.strip():
                up_list = json.loads(up_raw)
                update_count = len(up_list)
                update_packages = [
                    {
                        "name": p.get("Package", "?"),
                        "old":  p.get("OldVersion", "?"),
                        "new":  p.get("Version", "?"),
                    }
                    for p in up_list[:20]
                ]
        except Exception:
            pass

        return {
            "cpu_model":        cpu_model,
            "cpu_cores":        cpu_cores,
            "ram_total_mb":     ram_total_mb,
            "ram_used_mb":      ram_used_mb,
            "ram_percent":      ram_percent,
            "uptime_sec":       uptime_pve or uptime_sec,
            "load_avg":         load_avg,
            "temperatures":     temps,
            "kernel":           kernel_version,
            "pve_version":      pve_version,
            "vm_count":         vm_count,
            "ct_count":         ct_count,
            "last_backup_ts":   last_backup_ts,
            "storages":         storages,
            "update_count":     update_count,
            "update_packages":  update_packages,
        }

    # ── Coordinator-Pflichtmethode ─────────────────────────────────────────────

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except Exception as err:
            raise UpdateFailed(f"Fehler beim Abrufen der Daten: {err}") from err


# ── SMART-Parser ──────────────────────────────────────────────────────────────

def _parse_smart(device: str, data: dict) -> dict:
    """Extrahiert relevante SMART-Felder aus smartctl -j Ausgabe."""
    result: dict = {
        "device":               device,
        "model":                (data.get("model_name") or
                                 data.get("model_family") or "Unknown").strip(),
        "serial":               (data.get("serial_number") or "N/A").strip(),
        "firmware":             (data.get("firmware_version") or "N/A").strip(),
        "capacity_bytes":       (data.get("user_capacity") or {}).get("bytes", 0),
        "interface":            (data.get("device") or {}).get("protocol", "Unknown"),
        "smart_passed":         (data.get("smart_status") or {}).get("passed"),
        "temperature":          None,
        "power_on_hours":       None,
        "tbw_tb":               None,
        "percent_used":         None,
        "reallocated_sectors":  None,
        "uncorrectable_errors": None,
    }

    # Temperatur
    temp_block = data.get("temperature") or {}
    if temp_block.get("current") is not None:
        result["temperature"] = temp_block["current"]

    # Betriebsstunden
    pot = data.get("power_on_time") or {}
    result["power_on_hours"] = pot.get("hours")

    # NVMe
    nvme = data.get("nvme_smart_health_information_log") or {}
    if nvme:
        result["interface"] = "NVMe"
        result["percent_used"] = nvme.get("percentage_used")
        if result["temperature"] is None and nvme.get("temperature") is not None:
            result["temperature"] = nvme["temperature"] - 273
        if result["power_on_hours"] is None:
            result["power_on_hours"] = nvme.get("power_on_hours")
        duw = nvme.get("data_units_written") or 0
        if duw:
            result["tbw_tb"] = round(duw * 512_000 / 1e12, 2)
        result["uncorrectable_errors"] = nvme.get("num_err_log_entries", 0)

    # SATA / ATA Attribute
    ata_table = (data.get("ata_smart_attributes") or {}).get("table") or []
    if ata_table:
        if result["interface"] == "Unknown":
            result["interface"] = "SATA"
        by_id = {a["id"]: a for a in ata_table}

        # Reallocated Sectors (ID 5)
        if 5 in by_id:
            result["reallocated_sectors"] = (by_id[5].get("raw") or {}).get("value", 0)

        # Temperatur (ID 190 / 194)
        for tid in (190, 194):
            if tid in by_id and result["temperature"] is None:
                raw_val = (by_id[tid].get("raw") or {}).get("value") or 0
                t = int(raw_val) & 0xFF
                if 0 < t < 120:
                    result["temperature"] = t

        # Wear: 231 = SSD Life Left, 233 = Media Wearout, 177 = Samsung Wear_Leveling_Count
        for wid in (231, 233, 177):
            if wid in by_id and result["percent_used"] is None:
                val = by_id[wid].get("value") or 100
                result["percent_used"] = 100 - val

        # TBW (ID 241 / 247)
        for twid in (241, 247):
            if twid in by_id and result["tbw_tb"] is None:
                lbas = (by_id[twid].get("raw") or {}).get("value") or 0
                if lbas:
                    result["tbw_tb"] = round(lbas * 512 / 1e12, 2)

        # Uncorrectable Errors (ID 187)
        if 187 in by_id:
            result["uncorrectable_errors"] = (
                by_id[187].get("raw") or {}
            ).get("value", 0)

    return result
