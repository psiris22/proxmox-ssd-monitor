# Proxmox SSD Monitor — Home Assistant Integration

Monitor your Proxmox host's SSD health directly in Home Assistant via SSH and S.M.A.R.T. data.

## Features

- **SMART Health** — passed / failed status per disk
- **Temperature** — current drive temperature in °C
- **Wear Out** — consumed lifetime in %
- **Total Bytes Written (TBW)** — in TB
- **Reallocated Sectors** — early warning for failing drives
- **Uncorrectable Errors** — critical error count
- One **HA Device per disk** — with model, serial, firmware as device attributes
- Configurable polling interval (default: every 30 minutes)
- Supports SATA and NVMe drives

## Requirements

### On your Proxmox host

```bash
apt install smartmontools
```

### In Home Assistant

- Home Assistant 2023.6 or newer
- HACS installed

---

## Installation via HACS

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add the URL of this repository, category: **Integration**
5. Click **Download** on "Proxmox SSD Monitor"
6. Restart Home Assistant

## Manual Installation

1. Copy the `custom_components/proxmox_ssd_monitor` folder into your HA config directory:
   ```
   config/custom_components/proxmox_ssd_monitor/
   ```
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Proxmox SSD Monitor**
3. Fill in:
   - **Host / IP** — your Proxmox IP or hostname (e.g. `192.168.1.10`)
   - **SSH Port** — default `22`
   - **Username** — default `root`
   - **Password** — your Proxmox root password
   - **Scan Interval** — how often to poll (in minutes, default `30`)

---

## Entities Created

For each disk found on the Proxmox host, the following sensors are created:

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.<disk>_smart_health` | OK / Failed / Unknown | Overall SMART status |
| `sensor.<disk>_temperature` | °C | Current drive temperature |
| `sensor.<disk>_wear_out` | % | Consumed lifetime (0 = new, 100 = worn out) |
| `sensor.<disk>_total_bytes_written` | TB | Total data written to the drive |
| `sensor.<disk>_reallocated_sectors` | count | Remapped bad sectors (>0 = warning) |
| `sensor.<disk>_uncorrectable_errors` | count | Unrecoverable read/write errors |

All sensors belonging to the same disk are grouped under a single **Device** in HA, showing model, serial number, and firmware version.

---

## Example Automation

Send a notification if a drive's SMART health fails:

```yaml
automation:
  - alias: "SSD Health Alert"
    trigger:
      - platform: state
        entity_id: sensor.sda_smart_health
        to: "Failed"
    action:
      - service: notify.mobile_app
        data:
          message: "⚠️ SSD sda on Proxmox reports SMART failure!"
```

---

## Troubleshooting

**Cannot connect** — Check that SSH is enabled on Proxmox and the credentials are correct. Test from terminal: `ssh root@<your-proxmox-ip>`

**No disks found** — Make sure `smartmontools` is installed: `apt install smartmontools`

**Sensors show `Unknown`** — The drive may not support SMART or the specific attribute. This is normal for some older drives.

---

## License

MIT
