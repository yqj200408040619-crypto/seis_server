# miniSEED Web Portal

This project adds a browser-based customer portal on top of the existing `mseed-tcp-server` receiver.

It does **not** replace the TCP receiver. The TCP receiver writes one per-instrument HDF5 (`.h5`) file under:

```text
/var/lib/mseed-tcp-server/devices/
```

The web portal reads those databases in read-only mode and provides:

- customer login
- admin user management
- device permission assignment
- live waveform view
- historical waveform query
- three-component visualization for BHZ/BHN/BHE or other channel keys
- device keys such as `SS_02003` and `QS_02003`

## Architecture

```text
Seismic instrument
      ↓ TCP miniSEED
mseed-tcp-server :18000
      ↓ HDF5 files
/var/lib/mseed-tcp-server/devices/*.h5
      ↓ read-only
mseed-web-portal :8080
      ↓ reverse proxy
nginx :80 / optional HTTPS
      ↓
Browser login + waveform UI
```

## Install on Ubuntu 22.04

Upload and unzip the project, then run:

```bash
cd mseed_web_portal_project
sudo bash install.sh
```

Create an admin user:

```bash
sudo /opt/mseed-web-portal/.venv/bin/python \
/opt/mseed-web-portal/tools/create_admin.py \
--username admin \
--role admin
```

Sync existing receiver databases:

```bash
sudo /opt/mseed-web-portal/.venv/bin/python \
/opt/mseed-web-portal/tools/sync_devices.py
```

Open:

```text
http://<server-ip>/
```

## Admin workflow

1. Login as admin.
2. Go to **管理**.
3. Click **同步设备**.
4. Create customer users.
5. Grant each user access to the relevant devices.

A normal user can only see devices assigned to their account.

## Device key convention

For a stream like:

```text
SS.02003.00.BHZ
SS.02003.00.BHN
SS.02003.00.BHE
```

The portal uses:

```text
instrument_type   = SS
instrument_serial = 02003
device_key        = SS_02003
component_key     = BHZ / BHN / BHE
```

For a compact integrated instrument:

```text
QS.02003.00.BHZ
```

The device key becomes:

```text
QS_02003
```

## Services

Check web service:

```bash
sudo systemctl status mseed-web-portal
sudo journalctl -u mseed-web-portal -f
```

Check nginx:

```bash
sudo systemctl status nginx
sudo nginx -t
```

Restart:

```bash
sudo systemctl restart mseed-web-portal
sudo systemctl reload nginx
```

## Configuration

Main config:

```bash
sudo nano /etc/mseed-web-portal/portal.ini
```

Important fields:

```ini
[paths]
receiver_db_dir = /var/lib/mseed-tcp-server/devices
app_db = /var/lib/mseed-web-portal/app.db

[ui]
brand = Seismic Data Portal
refresh_seconds = 2
latest_default_seconds = 120
max_plot_points = 6000
max_query_records = 20000
```

After changes:

```bash
sudo systemctl restart mseed-web-portal
```

## HTTPS recommendation

For customer-facing deployment, put the portal behind HTTPS.

If you have a domain name pointing to the server, install Certbot and request a certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your.domain.com
```

If you do not have a domain, access by HTTP first for internal testing, then add a domain before giving access to customers.

## Firewall

For web access:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

For the TCP receiver:

```bash
sudo ufw allow 18000/tcp
```

For production, restrict TCP 18000 to instrument source IPs when possible.

## Query API

Authenticated users can call:

```text
GET /api/devices
GET /api/components?device_id=1
GET /api/waveform?device_id=1&component=BHZ&seconds=120
GET /api/waveform?device_id=1&component=BHZ&start=2026-06-30T15:30:00Z&end=2026-06-30T15:35:00Z
```

The API returns downsampled waveform points for browser plotting.

## Notes and limitations

- The portal reads waveforms and metadata from the receiver's HDF5 files in read-only mode.
- It does not modify raw receiver data.
- Very long historical queries are downsampled to keep the browser responsive.
- If a user needs raw miniSEED export, keep using the receiver project's `export_mseed.py` tool or add a controlled export endpoint later.
- True backfill of missing data still requires instrument-side resend support.
