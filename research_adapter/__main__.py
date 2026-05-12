from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("MEETYOU_RESEARCH_ADAPTER_HOST", "127.0.0.1")
    port = int(os.environ.get("MEETYOU_RESEARCH_ADAPTER_PORT", "8011") or 8011)
    uvicorn.run("research_adapter.service:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
