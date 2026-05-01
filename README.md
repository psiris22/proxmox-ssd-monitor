# Proxmox SSD Monitor — Home Assistant Integration

Monitor your Proxmox host's SSD health, system metrics, storage usage, and more — directly in Home Assistant via SSH and S.M.A.R.T. data.

---

## Features

**Per-disk sensors (SMART)**
- SMART Health — passed / failed status
- Temperature — current drive temperature in °C
- Wear Out — consumed lifetime in % (incl. Samsung SATA attribute 177)
- Total Bytes Written (TBW) — in TB
- Power On Hours
- Reallocated Sectors — early warning for failing drives
- Uncorrectable Errors — critical error count

**Host system sensors**
- RAM Usage — % used, total MB, used MB
- Uptime — in seconds (HA calculates human-readable duration)
- Load Average — 1 / 5 / 15 min
- Running VMs & Containers — live guest count
- Pending Updates — number of available APT packages (with package list as attribute)
- Last Backup — timestamp of the most recent vzdump job
- Proxmox VE Version
- Kernel Version
- Temperature sensors per thermal zone (CPU, chassis, …)

**Storage sensors**
- One sensor per active Proxmox storage (e.g. local-btrfs, NAS/CIFS)
- Shows usage in %, with total/used/free GB as attributes

---

## Requirements

**On your Proxmox host**
```bash
apt install smartmontools
```

**In Home Assistant**
- Home Assistant 2023.6 or newer
- HACS installed

---

## Installation via HACS

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add: `https://github.com/psiris22/proxmox-ssd-monitor` — Category: **Integration**
5. Click **Download** on "Proxmox SSD Monitor"
6. Restart Home Assistant

## Manual Installation

Copy the `custom_components/proxmox_ssd_monitor` folder into your HA config directory:
```
config/custom_components/proxmox_ssd_monitor/
```
Then restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Proxmox SSD Monitor**
3. Fill in:
   - **Host / IP** — your Proxmox IP or hostname (e.g. `192.168.22.202`)
   - **SSH Port** — default `22`
   - **Username** — default `root`
   - **Password** — your Proxmox root password
   - **Scan Interval** — polling interval in minutes (default: `30`)

---

## Entities Created

### Per disk

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.<disk>_smart_health` | OK / Failed / Unknown | Overall SMART status |
| `sensor.<disk>_temperature` | °C | Current drive temperature |
| `sensor.<disk>_wear_out` | % | Consumed lifetime |
| `sensor.<disk>_total_bytes_written` | TB | Total data written |
| `sensor.<disk>_power_on_hours` | h | Total operating hours |
| `sensor.<disk>_reallocated_sectors` | count | Remapped bad sectors |
| `sensor.<disk>_uncorrectable_errors` | count | Unrecoverable errors |

### Host system

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.proxmox_host_ram_usage` | % | RAM utilization |
| `sensor.proxmox_host_ram_used` | MB | RAM used |
| `sensor.proxmox_host_ram_total` | MB | Total RAM |
| `sensor.proxmox_host_uptime` | s | Host uptime |
| `sensor.proxmox_host_running_vms` | count | Active virtual machines |
| `sensor.proxmox_host_running_containers` | count | Active LXC containers |
| `sensor.proxmox_host_pending_updates` | count | Available APT updates |
| `sensor.proxmox_host_last_backup` | timestamp | Last vzdump job |
| `sensor.proxmox_host_proxmox_ve_version` | — | PVE version string |
| `sensor.proxmox_host_kernel_version` | — | Linux kernel version |
| `sensor.proxmox_host_temperature_<zone>` | °C | Per thermal zone |

### Per storage

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.proxmox_host_storage_<name>` | % | Storage utilization |

Attributes: `total_gb`, `used_gb`, `avail_gb`, `type`

---

## Example Automations

**Alert on SMART failure:**
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
          message: "⚠️ SSD /dev/sda on Proxmox reports SMART failure!"
```

**Alert when updates are available:**
```yaml
automation:
  - alias: "Proxmox Updates Available"
    trigger:
      - platform: numeric_state
        entity_id: sensor.proxmox_host_pending_updates
        above: 0
    action:
      - service: notify.mobile_app
        data:
          message: "📦 {{ states('sensor.proxmox_host_pending_updates') }} Proxmox updates available"
```

**Alert on high storage usage:**
```yaml
automation:
  - alias: "Proxmox Storage Warning"
    trigger:
      - platform: numeric_state
        entity_id: sensor.proxmox_host_storage_local_btrfs
        above: 85
    action:
      - service: notify.mobile_app
        data:
          message: "⚠️ Proxmox storage local-btrfs is above 85% full!"
```

---

## Troubleshooting

**Cannot connect** — Check that SSH is enabled and credentials are correct: `ssh root@<proxmox-ip>`

**No disks found** — Install smartmontools: `apt install smartmontools`

**Sensors show `Unknown`** — The drive may not support that SMART attribute. Normal for some drives.

**No host sensors** — Requires `pvesh` (included with Proxmox VE). Won't work on plain Debian.

---

## License

MIT
