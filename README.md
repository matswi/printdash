# Printdash

A modern, lightweight web interface for CUPS. Built for a Raspberry Pi that shares a USB printer on the network, but it works on any Linux machine running CUPS.

- Printer overview with live status
- Queue with active jobs and history: hold, release, cancel, reprint
- Drag and drop a file to print straight from the browser or your phone
- Pause/resume printers, print a test page, change the default printer, clear the queue
- Light and dark mode, works on mobile
- Optional password
- Mock mode for development without CUPS

CUPS still does all the heavy lifting (drivers, firmware, IPP sharing). Printdash is just a new face on top of it.

## Installing on the Pi

```bash
git clone https://github.com/matswi/printdash.git
cd printdash
sudo ./deploy/install.sh
```

Then open `http://<pi-ip>:8080`.

The script installs `python3-cups`, creates the system user `printdash` (a member of `lpadmin`), puts the app in `/opt/printdash` and starts it as a systemd service.

**Updating:** `git pull && sudo ./deploy/install.sh`

### Password

Edit `/etc/printdash.env`:

```
PRINTDASH_PASSWORD=your-password
```

and run `sudo systemctl restart printdash`. The browser will then ask you to log in (any username works).

### Settings

| Variable | Default | Description |
|---|---|---|
| `PRINTDASH_PASSWORD` | – | Require a password if set |
| `PRINTDASH_MAX_UPLOAD_MB` | `50` | Largest file that can be uploaded |
| `PRINTDASH_MOCK` | – | `1` = simulated printers instead of CUPS |

The port is set in `deploy/printdash.service`.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
PRINTDASH_MOCK=1 uvicorn app.main:app --reload --port 8080
```

Mock mode simulates an HP LaserJet 1020 that prints roughly one page every four seconds. Run the tests with `pytest`.

API documentation is available at `/api/docs`.

### Layout

```
app/
  backend.py   CupsBackend (pycups) and MockBackend
  main.py      FastAPI routes
  static/      Frontend (vanilla JS, no build step)
deploy/        systemd service and install script
tests/         API tests against the mock backend
```

## Troubleshooting

- **"Could not reach CUPS"**: check that CUPS is running (`systemctl status cups`).
- **Actions fail with "Forbidden"**: check that `printdash` is a member of `lpadmin` (`id printdash`) and that `lpadmin` is listed under `SystemGroup` in `/etc/cups/cups-files.conf`.
- **Reprint doesn't work**: CUPS only keeps job files for a limited time. See `PreserveJobFiles` in `/etc/cups/cupsd.conf`.
- **Logs**: `journalctl -u printdash -f`
