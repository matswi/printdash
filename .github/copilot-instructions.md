# Printdash – notes for reviewers

Printdash is a small web interface for CUPS, meant to run on a Raspberry Pi that shares a USB printer (an HP LaserJet 1020) on a home network.

## Architecture

- `app/backend.py` has two backends with the same interface:
  - `CupsBackend` talks to the local CUPS server through `pycups`. pycups connections are not thread-safe, so every call goes through `_call()`, which holds a lock and turns CUPS errors into `BackendError`.
  - `MockBackend` simulates printers and jobs in memory. It is used for development and in all tests (`PRINTDASH_MOCK=1`).
  - Any change to one backend's behaviour should be mirrored in the other.
- `app/main.py` is a FastAPI app. `BackendError` becomes an HTTP 400 with `{"detail": ...}`, which the frontend shows to the user.
- `app/static/` is a vanilla JavaScript frontend with no build step and no dependencies. It polls the API every 2 seconds.
- `deploy/` has a systemd unit and an install script for Raspberry Pi OS (Debian Bookworm, Python 3.11).

## What to watch for in reviews

- **Security:** the app can be exposed to the whole local network. Uploaded files and form fields must be validated before they reach CUPS (file type, size, copies, page ranges). The optional password (`PRINTDASH_PASSWORD`) must protect every route except `/api/health`.
- **Least privilege:** the service runs as the `printdash` user in the `lpadmin` group, never as root.
- **Raspberry Pi constraints:** keep dependencies minimal and avoid anything heavy at runtime.
- **Frontend:** build DOM nodes with `textContent`, never `innerHTML` with server data. Keep it working on phones and in both light and dark mode.
- **Tests:** new API behaviour should come with a test in `tests/` that runs against `MockBackend`.

All text, including UI strings, comments and docs, is in English.
When settings, environment variables or deployment steps change, the README should be updated in the same PR.
