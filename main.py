#!/usr/bin/env python3
"""Start Auty API server. Live camera is in the dashboard (browser), not a native window."""

import socket
import sys
import threading
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import uvicorn
from server.main import app as app

_CERTS_DIR = Path(__file__).parent / "certs"
_CERT = _CERTS_DIR / "server.crt"
_KEY = _CERTS_DIR / "server.key"

_HTTP_PORT = 8000   # Mac browser — http://localhost:8000
_HTTPS_PORT = 8443  # iPad over LAN — https://<lan-ip>:8443


def _lan_ip() -> str:
    """Best-effort LAN IP — doesn't actually send packets, just picks the
    interface that would route to the internet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


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
        print(f"[Auty] HTTPS → https://{_lan_ip()}:{_HTTPS_PORT}  (iPad — install certs/rootCA.pem first)")
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
