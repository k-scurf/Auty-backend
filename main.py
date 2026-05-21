#!/usr/bin/env python3
"""Start Auty API server (React dashboard at http://localhost:5173 in dev)."""

import uvicorn


def main():
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
