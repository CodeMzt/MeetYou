from __future__ import annotations

import argparse
import logging

from core.config import ConfigManager
from core.db.bootstrap import bootstrap_core_domain
from core.db.importers import import_config_state, import_memory_state, import_source_catalog_state, import_task_state


logger = logging.getLogger("meetyou.migrate_to_core_db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import current MeetYou state into Core database")
    parser.add_argument("--skip-config", action="store_true")
    parser.add_argument("--skip-memory", action="store_true")
    parser.add_argument("--skip-source-catalog", action="store_true")
    parser.add_argument("--skip-tasks", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    config = ConfigManager()
    context = bootstrap_core_domain(config, run_migrations=True)

    if not args.skip_config:
        logger.info("Imported %s config entries", import_config_state(config, context.services))
    if not args.skip_memory:
        logger.info(
            "Imported %s memory records",
            import_memory_state(
                config.get("memory_file_path") or "user/memory_graph.json",
                principal_id=context.principal.id,
                workspaces=context.workspaces,
                services=context.services,
            ),
        )
    if not args.skip_source_catalog:
        logger.info(
            "Imported %s source catalog entries",
            import_source_catalog_state(
                config.get("source_catalog_path") or "user/source_catalog.json",
                principal_id=context.principal.id,
                services=context.services,
            ),
        )
    if not args.skip_tasks:
        logger.info(
            "Imported %s task records",
            import_task_state(
                config.get("task_file_path") or "user/memory_tasks.json",
                principal_id=context.principal.id,
                workspaces=context.workspaces,
                services=context.services,
            ),
        )
    context.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
