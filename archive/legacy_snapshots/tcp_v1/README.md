# mseed-tcp-server

A deployable TCP miniSEED receiver for seismic instruments on Ubuntu 22.04.

The server accepts TCP connections from instruments, reconstructs complete miniSEED records from the TCP byte stream, validates each record with ObsPy, classifies data by client IP/server port/station, and stores each instrument's raw miniSEED packets in its own SQLite database.

## 1. Design scope

Implemented:

- TCP server for multiple concurrent instruments.
- Correct TCP byte-stream buffering. One `recv()` call is not treated as one miniSEED packet.
- miniSEED 2.x record-length parsing from Blockette 1000.
- Optional fixed record length fallback.
- ObsPy validation of complete miniSEED records.
- One SQLite database per instrument.
- Raw packet BLOB storage.
- Duplicate packet suppression.
- Sequence-gap and time-gap detection.
- Server restart recovery by persistent database state.
- Disconnect handling and partial-buffer quarantine.
- Malformed-data resynchronization.
- systemd deployment.

Not universally implementable without device-side support:

- True protocol-level retransmission of missing records. The server can detect missing sequence/time ranges and suppress duplicates, but a generic miniSEED-over-TCP sender has no standard command for "resend from sequence N" unless the instrument firmware implements such a protocol.

## 2. Directory layout after installation

```text
/opt/mseed-tcp-server/                 application code and Python venv
/etc/mseed-tcp-server/server.ini       runtime configuration
/var/lib/mseed-tcp-server/devices/     one SQLite .db file per instrument
/var/lib/mseed-tcp-server/quarantine/  bad/partial/unrecoverable byte fragments
/var/log/mseed-tcp-server/server.log   rotating application log
```

## 3. Install on Ubuntu 22.04

Copy this project directory to the server, then run:

```bash
cd mseed_tcp_server_project
sudo bash install.sh
```

Edit the TCP port if required:

```bash
sudo nano /etc/mseed-tcp-server/server.ini
```

Start the service:

```bash
sudo systemctl start mseed-tcp-server
sudo systemctl status mseed-tcp-server
```

Watch logs:

```bash
sudo journalctl -u mseed-tcp-server -f
sudo tail -f /var/log/mseed-tcp-server/server.log
```

Enable firewall access if UFW is enabled:

```bash
sudo ufw allow 18000/tcp
```

## 4. Configuration

Main configuration file:

```ini
[server]
host = 0.0.0.0
port = 18000
recv_size = 8192
socket_timeout_sec = 120
tcp_keepalive = true
max_clients = 256

[storage]
base_dir = /var/lib/mseed-tcp-server
log_dir = /var/log/mseed-tcp-server

[parser]
fixed_record_length = 0
validate_with_obspy = true
store_unvalidated_packets = false
time_gap_tolerance_samples = 1.5
```

`fixed_record_length = 0` means the server reads the record length from miniSEED Blockette 1000. If your instrument always sends fixed-size records but omits Blockette 1000, set this to `512`, `1024`, `2048`, or `4096`.

## 5. Database schema

Each instrument has one database:

```text
/var/lib/mseed-tcp-server/devices/<client_ip>_<server_port>_<network>_<station>.db
```

Main tables:

- `packets`: validated raw miniSEED records.
- `stream_state`: latest checkpoint per stream, used for restart recovery and gap detection.
- `gaps`: detected sequence/time gaps and overlaps.
- `events`: duplicate-packet and operational events.

Important fields in `packets`:

- `start_unix`: miniSEED record start time in UNIX seconds.
- `end_unix`: estimated next-record start time based on `npts / sampling_rate`.
- `seq_no`: miniSEED sequence number from the first 6 record bytes.
- `raw_mseed`: original raw miniSEED record as BLOB.
- `sha256`: packet checksum.
- `network`, `station`, `location`, `channel`: stream identity.

## 6. Interruption, loss, validation, resume

### 6.1 TCP interruption

If an instrument disconnects, the server closes that connection and preserves already committed packets. The partial bytes left in the current TCP buffer are written to quarantine because they are not a complete miniSEED record.

### 6.2 Server restart

SQLite databases and `stream_state` are persistent. After `systemctl restart mseed-tcp-server`, new packets are appended to the existing database. Duplicate packets after reconnection are ignored by database uniqueness constraints.

### 6.3 Data loss detection

The server detects two classes of discontinuity:

1. `sequence_gap`: the current miniSEED sequence number does not equal the previous sequence number plus one.
2. `time_gap` / `time_overlap`: the current start time does not match the previous record's expected end time within the configured tolerance.

These events are stored in the `gaps` table and written to the log.

### 6.4 Data validation

Each complete record is parsed with ObsPy. If ObsPy cannot parse the record and `store_unvalidated_packets = false`, the record is not written to the device database and is written to quarantine.

### 6.5 True breakpoint resume

This server supports receiver-side resume: it keeps all committed data and rejects duplicates after reconnect. It does not automatically request missing data from the device because raw miniSEED-over-TCP does not define a universal retransmission command. If your instrument supports a custom resend command, add a device-protocol layer that queries `stream_state` and asks the instrument to resend from the last stored `start_unix` or `seq_no`.

## 7. Check status

```bash
sudo /opt/mseed-tcp-server/.venv/bin/python /opt/mseed-tcp-server/tools/check_status.py
```

or for a custom DB directory:

```bash
python3 tools/check_status.py /var/lib/mseed-tcp-server/devices
```

## 8. Export raw miniSEED

Export an entire device database:

```bash
python3 tools/export_mseed.py \
  /var/lib/mseed-tcp-server/devices/DEVICE.db \
  output.mseed
```

Export a single stream and time range:

```bash
python3 tools/export_mseed.py \
  /var/lib/mseed-tcp-server/devices/DEVICE.db \
  output.mseed \
  --stream XX.STA01.00.BHZ \
  --start 1780000000 \
  --end 1780003600
```

## 9. Test with a local miniSEED file

Start the service, then send a known miniSEED file:

```bash
python3 tools/send_mseed_file.py sample.mseed --host 127.0.0.1 --port 18000 --chunk 1500
```

Using a small TCP chunk size tests whether the receiver correctly reconstructs records across arbitrary TCP boundaries.

## 10. Operational notes

- Use SSD-backed storage for high-rate continuous acquisition.
- Back up `/var/lib/mseed-tcp-server/devices` regularly.
- Watch the `gaps` table and log warnings; they are the primary evidence of transmission loss or device reset.
- Keep `store_unvalidated_packets = false` in production unless you intentionally want to preserve invalid records in the device database.
- If many instruments connect through the same NAT IP, keep station/network fields correct in the miniSEED header; the database name uses both IP and station.
