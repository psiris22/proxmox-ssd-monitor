"""Config Flow für Proxmox SSD Monitor."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DEFAULT_SCAN_INTERVAL,
)

STEP_SCHEMA = vol.Schema(
    {
        vol.Required("host"):                               str,
        vol.Optional("port",          default=DEFAULT_PORT):          int,
        vol.Optional("username",      default=DEFAULT_USERNAME):      str,
        vol.Required("password"):                           str,
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): int,
    }
)


async def _validate_connection(hass: HomeAssistant, data: dict) -> None:
    """Testet die SSH-Verbindung – wirft Exception bei Fehler."""

    def _test() -> None:
        import paramiko  # noqa: PLC0415

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=data["host"],
            port=int(data.get("port", DEFAULT_PORT)),
            username=data.get("username", DEFAULT_USERNAME),
            password=data.get("password", ""),
            timeout=15,
            banner_timeout=15,
        )
        # Kurzer Smoke-Test
        stdin, stdout, stderr = client.exec_command("echo ok", timeout=5)
        stdout.read()
        client.close()

    await hass.async_add_executor_job(_test)


class ProxmoxSSDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Einrichtungsassistent für Proxmox SSD Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Doppelt-Konfiguration verhindern
            await self.async_set_unique_id(user_input["host"])
            self._abort_if_unique_id_configured()

            try:
                await _validate_connection(self.hass, user_input)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Proxmox – {user_input['host']}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
