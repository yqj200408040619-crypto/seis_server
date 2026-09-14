# Seismic TCP Server and Web Portal

This repository contains the deployable source for the seismic miniSEED TCP receiver and its HDF5-backed web portal.

## Components

- `mseed_tcp_server_realtime/`: TCP receiver, miniSEED parsing and per-device HDF5 storage.
- `mseed_web_portal_realtime/`: FastAPI web portal, authentication, permissions and waveform queries.
- `MSEED_TCP_WEBPORTAL_系统说明_CN.md`: architecture, storage layout and deployment notes.

The current production layout is `/opt/mseed-tcp-server` and `/opt/mseed-web-portal`. Runtime data is deliberately excluded from Git:

- `/var/lib/mseed-tcp-server/devices/*.h5`: waveform data.
- `/var/lib/mseed-web-portal/app.db`: users, permissions and portal metadata.

Copy `config/*.ini` to a machine-local configuration and set secrets there. Never commit passwords, tokens or runtime databases.

## Deployment

Each component contains its own `install.sh`, `requirements.txt`, systemd unit and README. Review the configuration and run the installer on a Debian/Ubuntu host with appropriate privileges.

