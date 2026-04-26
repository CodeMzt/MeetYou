from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build_info import package_version_from_env, resolve_build_info, write_build_info


def _read_ui_package_version(repo_root: Path) -> str:
    package_json_path = repo_root / "meetyou-ui" / "package.json"
    payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    return str(payload.get("version") or "0.0.0")


def main() -> None:
    repo_root = REPO_ROOT
    ui_package_version = _read_ui_package_version(repo_root)

    definitions = [
        {
            "component": "core",
            "package_version": package_version_from_env("MEETYOU_CORE_PACKAGE_VERSION", ui_package_version),
            "path": repo_root / "core" / "build_info.json",
        },
        {
            "component": "desktop_backend",
            "package_version": package_version_from_env("MEETYOU_DESKTOP_BACKEND_PACKAGE_VERSION", ui_package_version),
            "path": repo_root / "desktop_client" / "build_info.json",
        },
        {
            "component": "ui",
            "package_version": package_version_from_env("MEETYOU_UI_PACKAGE_VERSION", ui_package_version),
            "path": repo_root / "meetyou-ui" / "src" / "generated" / "build_info.json",
        },
    ]

    for item in definitions:
        payload = resolve_build_info(
            component=item["component"],
            package_version=item["package_version"],
            cwd=repo_root,
        )
        write_build_info(item["path"], payload)
        print(f"generated {item['component']}: {item['path']}")


if __name__ == "__main__":
    main()
