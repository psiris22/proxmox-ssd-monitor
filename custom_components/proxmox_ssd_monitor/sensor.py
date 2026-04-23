"""Sensor-Entitäten für Proxmox SSD Monitor."""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ProxmoxSSDSensorDescription(SensorEntityDescription):
    """Erweiterter Sensor-Descriptor mit optionalem Attribut-Key."""
    data_key: str = ""


# ── Sensor-Definitionen ───────────────────────────────────────────────────────

SENSOR_TYPES: tuple[ProxmoxSSDSensorDescription, ...] = (
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


# ── Setup ─────────────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProxmoxSSDCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_disks: set[str] = set()

    def _add_new_disks() -> None:
        if not coordinator.data:
            return
        new_entities: list[ProxmoxSSDSensor] = []
        for disk_name in coordinator.data:
            if disk_name not in known_disks:
                known_disks.add(disk_name)
                for desc in SENSOR_TYPES:
                    new_entities.append(
                        ProxmoxSSDSensor(coordinator, entry, disk_name, desc)
                    )
        if new_entities:
            async_add_entities(new_entities)

    # Initial setup
    _add_new_disks()

    # Dynamisch neue Disks hinzufügen wenn der Coordinator aktualisiert
    entry.async_on_unload(
        coordinator.async_add_listener(_add_new_disks)
    )


# ── Sensor-Klasse ─────────────────────────────────────────────────────────────

class ProxmoxSSDSensor(CoordinatorEntity[ProxmoxSSDCoordinator], SensorEntity):
    """Repräsentiert einen einzelnen SMART-Messwert einer SSD."""

    entity_description: ProxmoxSSDSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ProxmoxSSDCoordinator,
        entry: ConfigEntry,
        disk_name: str,
        description: ProxmoxSSDSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._disk_name = disk_name
        self._entry = entry

        host = entry.data["host"]
        self._attr_unique_id = f"{DOMAIN}_{host}_{disk_name}_{description.key}"

    # ── Device Info (eine HA-Device pro Disk) ─────────────────────────────

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
            via_device=None,
        )

    # ── Zustand ───────────────────────────────────────────────────────────

    @property
    def _disk_data(self) -> dict:
        return (self.coordinator.data or {}).get(self._disk_name, {})

    @property
    def native_value(self) -> Any:
        disk = self._disk_data
        key = self.entity_description.data_key

        if self.entity_description.key == "smart_health":
            passed = disk.get("smart_passed")
            if passed is True:
                return "OK"
            if passed is False:
                return "Failed"
            return "Unknown"

        return disk.get(key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Zusatzinfos nur am SMART-Health-Sensor."""
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
        """SMART Health bekommt rotes Icon wenn failed."""
        if self.entity_description.key == "smart_health":
            if self._disk_data.get("smart_passed") is False:
                return "mdi:shield-alert"
        return self.entity_description.icon or ""
