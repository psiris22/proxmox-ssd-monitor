"""Sensor-Entitäten für Proxmox SSD Monitor."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProxmoxSSDCoordinator


# ── Sensor-Descriptor-Klassen ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ProxmoxSSDSensorDescription(SensorEntityDescription):
    """Descriptor für SMART-Disk-Sensoren."""
    data_key: str = ""


@dataclass(frozen=True)
class ProxmoxHostSensorDescription(SensorEntityDescription):
    """Descriptor für Host-Sensoren."""
    data_key: str = ""


# ── Disk / SMART Sensoren ─────────────────────────────────────────────────────

DISK_SENSOR_TYPES: tuple[ProxmoxSSDSensorDescription, ...] = (
    ProxmoxSSDSensorDescription(
        key="smart_health",
        data_key="smart_passed",
        name="SMART Health",
        icon="mdi:shield-check",
    ),
    ProxmoxSSDSensorDescription(
        key="temperature",
        data_key="temperature",
        name="Temperature",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
    ),
    ProxmoxSSDSensorDescription(
        key="percent_used",
        data_key="percent_used",
        name="Wear Out",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-low",
    ),
    ProxmoxSSDSensorDescription(
        key="tbw_tb",
        data_key="tbw_tb",
        name="Total Bytes Written",
        native_unit_of_measurement="TB",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:database-arrow-up",
    ),
    ProxmoxSSDSensorDescription(
        key="power_on_hours",
        data_key="power_on_hours",
        name="Power On Hours",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:clock-outline",
    ),
    ProxmoxSSDSensorDescription(
        key="reallocated_sectors",
        data_key="reallocated_sectors",
        name="Reallocated Sectors",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle",
    ),
    ProxmoxSSDSensorDescription(
        key="uncorrectable_errors",
        data_key="uncorrectable_errors",
        name="Uncorrectable Errors",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:close-circle",
    ),
)


# ── Host-Sensoren ─────────────────────────────────────────────────────────────

HOST_SENSOR_TYPES: tuple[ProxmoxHostSensorDescription, ...] = (
    ProxmoxHostSensorDescription(
        key="ram_percent",
        data_key="ram_percent",
        name="RAM Usage",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
    ProxmoxHostSensorDescription(
        key="ram_used_mb",
        data_key="ram_used_mb",
        name="RAM Used",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
    ProxmoxHostSensorDescription(
        key="ram_total_mb",
        data_key="ram_total_mb",
        name="RAM Total",
        native_unit_of_measurement="MB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
    ProxmoxHostSensorDescription(
        key="uptime_sec",
        data_key="uptime_sec",
        name="Uptime",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
    ),
    ProxmoxHostSensorDescription(
        key="vm_count",
        data_key="vm_count",
        name="Running VMs",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:server",
    ),
    ProxmoxHostSensorDescription(
        key="ct_count",
        data_key="ct_count",
        name="Running Containers",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:docker",
    ),
    ProxmoxHostSensorDescription(
        key="update_count",
        data_key="update_count",
        name="Pending Updates",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:package-up",
    ),
    ProxmoxHostSensorDescription(
        key="last_backup",
        data_key="last_backup_ts",
        name="Last Backup",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:backup-restore",
    ),
    ProxmoxHostSensorDescription(
        key="pve_version",
        data_key="pve_version",
        name="Proxmox VE Version",
        icon="mdi:information-outline",
    ),
    ProxmoxHostSensorDescription(
        key="kernel",
        data_key="kernel",
        name="Kernel Version",
        icon="mdi:linux",
    ),
)


# ── Setup ─────────────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProxmoxSSDCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_disks: set[str] = set()
    host_added = False

    def _add_entities() -> None:
        nonlocal host_added
        if not coordinator.data:
            return

        new_entities: list = []

        # ── Disk-Sensoren ──────────────────────────────────────────────
        disks = coordinator.data.get("disks", {})
        for disk_name in disks:
            if disk_name not in known_disks:
                known_disks.add(disk_name)
                for desc in DISK_SENSOR_TYPES:
                    new_entities.append(
                        ProxmoxSSDSensor(coordinator, entry, disk_name, desc)
                    )

        # ── Host-Sensoren (einmalig) ───────────────────────────────────
        if not host_added and coordinator.data.get("host"):
            host_added = True
            for desc in HOST_SENSOR_TYPES:
                new_entities.append(ProxmoxHostSensor(coordinator, entry, desc))

            # ── Storage-Sensoren (je Storage ein Sensor) ──────────────
            for storage in coordinator.data["host"].get("storages", []):
                new_entities.append(
                    ProxmoxStorageSensor(coordinator, entry, storage["name"])
                )

            # ── Temperatur-Sensoren (je Thermal Zone ein Sensor) ──────
            for zone_name in coordinator.data["host"].get("temperatures", {}):
                new_entities.append(
                    ProxmoxTempSensor(coordinator, entry, zone_name)
                )

        if new_entities:
            async_add_entities(new_entities)

    _add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_entities))


# ── Disk / SMART Sensor ───────────────────────────────────────────────────────

class ProxmoxSSDSensor(CoordinatorEntity[ProxmoxSSDCoordinator], SensorEntity):
    """Einzelner SMART-Messwert einer Festplatte."""

    entity_description: ProxmoxSSDSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, disk_name: str,
                 description: ProxmoxSSDSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._disk_name = disk_name
        self._entry = entry
        host = entry.data["host"]
        self._attr_unique_id = f"{DOMAIN}_{host}_{disk_name}_{description.key}"

    @property
    def _disk_data(self) -> dict:
        return (self.coordinator.data or {}).get("disks", {}).get(self._disk_name, {})

    @property
    def device_info(self) -> DeviceInfo:
        disk = self._disk_data
        host = self._entry.data["host"]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{host}_{self._disk_name}")},
            name=f"{disk.get('model', self._disk_name)} ({self._disk_name})",
            model=disk.get("model"),
            sw_version=disk.get("firmware"),
            serial_number=disk.get("serial"),
            manufacturer=_guess_manufacturer(disk.get("model", "")),
        )

    @property
    def native_value(self) -> Any:
        disk = self._disk_data
        if self.entity_description.key == "smart_health":
            passed = disk.get("smart_passed")
            if passed is True:
                return "OK"
            if passed is False:
                return "Failed"
            return "Unknown"
        return disk.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key != "smart_health":
            return None
        disk = self._disk_data
        return {
            "interface":      disk.get("interface"),
            "serial":         disk.get("serial"),
            "firmware":       disk.get("firmware"),
            "capacity_bytes": disk.get("capacity_bytes"),
            "power_on_hours": disk.get("power_on_hours"),
        }

    @property
    def icon(self) -> str:
        if self.entity_description.key == "smart_health":
            if self._disk_data.get("smart_passed") is False:
                return "mdi:shield-alert"
        return self.entity_description.icon or ""


# ── Host-Sensor ───────────────────────────────────────────────────────────────

class ProxmoxHostSensor(CoordinatorEntity[ProxmoxSSDCoordinator], SensorEntity):
    """Ein Host-Metrik-Sensor (CPU, RAM, Updates, …)."""

    entity_description: ProxmoxHostSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry,
                 description: ProxmoxHostSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        host = entry.data["host"]
        self._attr_unique_id = f"{DOMAIN}_{host}_host_{description.key}"

    @property
    def _host_data(self) -> dict:
        return (self.coordinator.data or {}).get("host", {})

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.data["host"]
        hd   = self._host_data
        return DeviceInfo(
            identifiers={(DOMAIN, f"{host}_host")},
            name=f"Proxmox Host ({host})",
            model=hd.get("cpu_model", "Proxmox VE"),
            sw_version=hd.get("pve_version"),
        )

    @property
    def native_value(self) -> Any:
        hd  = self._host_data
        key = self.entity_description.data_key

        if self.entity_description.key == "last_backup":
            ts = hd.get("last_backup_ts")
            if ts:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            return None

        return hd.get(key)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key == "update_count":
            return {"packages": self._host_data.get("update_packages", [])}
        if self.entity_description.key == "ram_percent":
            hd = self._host_data
            return {
                "total_mb": hd.get("ram_total_mb"),
                "used_mb":  hd.get("ram_used_mb"),
            }
        return None


# ── Storage-Sensor ────────────────────────────────────────────────────────────

class ProxmoxStorageSensor(CoordinatorEntity[ProxmoxSSDCoordinator], SensorEntity):
    """Auslastung eines Proxmox-Storage-Pools in Prozent."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:harddisk"

    def __init__(self, coordinator, entry, storage_name: str) -> None:
        super().__init__(coordinator)
        self._storage_name = storage_name
        self._entry = entry
        host = entry.data["host"]
        self._attr_unique_id = f"{DOMAIN}_{host}_storage_{storage_name}"
        self._attr_name = f"Storage {storage_name}"

    @property
    def _storage_data(self) -> dict:
        for s in (self.coordinator.data or {}).get("host", {}).get("storages", []):
            if s["name"] == self._storage_name:
                return s
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.data["host"]
        return DeviceInfo(identifiers={(DOMAIN, f"{host}_host")})

    @property
    def native_value(self) -> float | None:
        return self._storage_data.get("pct")

    @property
    def extra_state_attributes(self) -> dict | None:
        sd = self._storage_data
        return {
            "type":     sd.get("type"),
            "total_gb": sd.get("total_gb"),
            "used_gb":  sd.get("used_gb"),
            "avail_gb": sd.get("avail_gb"),
        }


# ── Temperatur-Sensor ─────────────────────────────────────────────────────────

class ProxmoxTempSensor(CoordinatorEntity[ProxmoxSSDCoordinator], SensorEntity):
    """Temperatur einer Thermal-Zone des Proxmox-Hosts."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "°C"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry, zone_name: str) -> None:
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._entry = entry
        host = entry.data["host"]
        self._attr_unique_id = f"{DOMAIN}_{host}_temp_{zone_name}"
        self._attr_name = f"Temperature {zone_name}"

    @property
    def device_info(self) -> DeviceInfo:
        host = self._entry.data["host"]
        return DeviceInfo(identifiers={(DOMAIN, f"{host}_host")})

    @property
    def native_value(self) -> float | None:
        return (
            (self.coordinator.data or {})
            .get("host", {})
            .get("temperatures", {})
            .get(self._zone_name)
        )


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _guess_manufacturer(model: str) -> str | None:
    m = model.upper()
    if "SAMSUNG" in m:
        return "Samsung"
    if "WD" in m or "WESTERN" in m:
        return "Western Digital"
    if "SEAGATE" in m or "ST" in m[:3]:
        return "Seagate"
    if "KINGSTON" in m:
        return "Kingston"
    if "CRUCIAL" in m:
        return "Crucial"
    if "INTEL" in m:
        return "Intel"
    if "SANDISK" in m:
        return "SanDisk"
    if "TOSHIBA" in m:
        return "Toshiba"
    return None
