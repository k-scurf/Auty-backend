#!/usr/bin/env python3
"""Start Auty API server. Live camera is in the dashboard (browser), not a native window."""

import threading
from pathlib import Path

import uvicorn
from server.main import app as app

_CERTS_DIR = Path(__file__).parent / "certs"
_CERT = _CERTS_DIR / "server.crt"
_KEY = _CERTS_DIR / "server.key"

_HTTP_PORT = 8000   # Mac browser — http://localhost:8000
_HTTPS_PORT = 8443  # iPad over LAN — https://192.168.1.100:8443


def _start_https():
    """HTTPS server for iPad/LAN access — runs in a background thread."""
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=_HTTPS_PORT,
        reload=False,
        log_level="warning",   # quieter — HTTP server shows the main logs
        ssl_certfile=str(_CERT),
        ssl_keyfile=str(_KEY),
        timeout_graceful_shutdown=2,
    )


def main():
    use_https = _CERT.is_file() and _KEY.is_file()

    if use_https:
        t = threading.Thread(target=_start_https, daemon=True, name="auty-https")
        t.start()
        print(f"[Auty] HTTP  → http://localhost:{_HTTP_PORT}  (Mac browser)")
        print(f"[Auty] HTTPS → https://192.168.1.100:{_HTTPS_PORT}  (iPad — install certs/rootCA.pem first)")
    else:
        print(f"[Auty] HTTP  → http://localhost:{_HTTP_PORT}")

    # HTTP server on 8000 blocks the main thread
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=_HTTP_PORT,
        reload=False,
        log_level="info",
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
