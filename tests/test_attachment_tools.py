from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.db.bootstrap import bootstrap_core_domain
from tools.attachment_tools import AttachmentTools


TEST_DATABASE_NAME = "meetyou_attachment_tools_test"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"


class AttachmentToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (TEST_DATABASE_NAME,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}"')
                cur.execute(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')

    @classmethod
    def tearDownClass(cls):
        import psycopg

        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (TEST_DATABASE_NAME,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}"')

    def test_attachment_tools_list_read_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                attachment, ticket = context.services.attachment.create_upload_ticket(
                    owner_type="thread",
                    owner_id="thr_tool_1",
                    issuer_type="client",
                    issuer_ref="desktop-app",
                    kind="file",
                    mime_type="text/plain",
                    file_name="notes.txt",
                )
                context.services.attachment.store_upload_content(ticket.ticket_id, b"tool-readable-text")
                context.services.attachment.complete_attachment(
                    attachment_id=attachment.attachment_id,
                    ticket_id=ticket.ticket_id,
                )

                tools = AttachmentTools()
                tools.set_core_domain(context)

                listed = asyncio.run(
                    tools.list_attachments(owner_type="thread", owner_id="thr_tool_1")
                )
                self.assertEqual(listed["count"], 1)
                self.assertEqual(listed["attachments"][0]["attachment_id"], attachment.attachment_id)
                self.assertTrue(listed["attachments"][0]["created_at"])
                self.assertTrue(listed["attachments"][0]["completed_at"])

                detail = asyncio.run(
                    tools.read_attachment(
                        attachment_id=attachment.attachment_id,
                        include_content=True,
                    )
                )
                self.assertEqual(detail["file_name"], "notes.txt")
                self.assertEqual(detail["content_text"], "tool-readable-text")
                self.assertEqual(detail["bytes_read"], len(b"tool-readable-text"))

                deleted = asyncio.run(
                    tools.delete_attachment(attachment_id=attachment.attachment_id)
                )
                self.assertEqual(deleted["status"], "deleted")
                self.assertTrue(deleted["deleted_at"])

                with self.assertRaisesRegex(RuntimeError, "Failed to read attachment metadata"):
                    asyncio.run(
                        tools.read_attachment(attachment_id=attachment.attachment_id)
                    )
            finally:
                context.engine.dispose()


if __name__ == "__main__":
    unittest.main()
