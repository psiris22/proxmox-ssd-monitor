"""DataUpdateCoordinator für Proxmox SSD Monitor."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_PORT, DEFAULT_USERNAME, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ProxmoxSSDCoordinator(DataUpdateCoordinator):
    """Koordiniert SSH-Abfragen zum Proxmox-Host alle N Minuten."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._entry = entry
        interval = entry.data.get(DOMAIN + "_scan_interval",
                   entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    # ── SSH-Hilfsmethoden (laufen im Executor-Thread) ──────────────────────

    def _make_client(self):
        """Neue SSH-Verbindung aufbauen und zurückgeben."""
        import paramiko  # lazy import – wird von HA installiert

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
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        return stdout.read().decode("utf-8", errors="replace")

    def _fetch(self) -> dict:
        """Holt SMART-Daten aller Disks – läuft im Thread-Pool."""
        client = self._make_client()
        try:
            # Festplatten ermitteln
            raw = self._run(client, "lsblk -o NAME,TYPE -J 2>/dev/null")
            disks: list[str] = []
            try:
                for dev in json.loads(raw).get("blockdevices", []):
                    if dev.get("type") == "disk":
                        disks.append(dev["name"])
            except (json.JSONDecodeError, KeyError):
                _LOGGER.warning("lsblk-Ausgabe konnte nicht geparst werden")

            result: dict = {}
            for disk in disks:
                raw_smart = self._run(
                    client, f"smartctl -a -j /dev/{disk} 2>/dev/null"
                )
                try:
                    result[disk] = _parse_smart(disk, json.loads(raw_smart))
                except (json.JSONDecodeError, Exception) as exc:
                    _LOGGER.debug("SMART-Parsing für %s fehlgeschlagen: %s", disk, exc)

            return result
        finally:
            client.close()

    # ── Coordinator-Pflichtmethode ─────────────────────────────────────────

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except Exception as err:
            raise UpdateFailed(f"Fehler beim Abrufen der SMART-Daten: {err}") from err


# Alias damit _make_client den richtigen Key findet
CONF_KEY_HOST = "host"


# ── SMART-Parser (reused from ssd_monitor.py) ─────────────────────────────

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

        # Wear / SSD Life Left (ID 231, 233)
        for wid in (231, 233):
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
