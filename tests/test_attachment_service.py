from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.db.bootstrap import bootstrap_core_domain


TEST_DATABASE_NAME = "meetyou_attachment_service_test"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"


class AttachmentServiceTests(unittest.TestCase):
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

    def test_attachment_service_uses_object_store_backend(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                attachment, ticket = context.services.attachment.create_upload_ticket(
                    owner_type="thread",
                    owner_id="thr_1",
                    issuer_type="client",
                    issuer_ref="desktop-app",
                    kind="file",
                    mime_type="text/plain",
                    file_name="note.txt",
                )
                uploaded = context.services.attachment.store_upload_content(ticket.ticket_id, b"hello-object-store")
                completed = context.services.attachment.complete_attachment(
                    attachment_id=attachment.attachment_id,
                    ticket_id=ticket.ticket_id,
                )
                resolved = context.services.attachment.resolve_attachment_path(attachment.attachment_id)

                self.assertEqual(uploaded.status, "uploaded")
                self.assertEqual(completed.status, "ready")
                self.assertTrue(resolved.exists())
                self.assertEqual(resolved.read_bytes(), b"hello-object-store")
            finally:
                context.engine.dispose()

    def test_attachment_service_builds_canonical_object_view(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                attachment, ticket = context.services.attachment.create_upload_ticket(
                    owner_type="operation",
                    owner_id="op_1",
                    issuer_type="agent",
                    issuer_ref="desktop-main-agent",
                    kind="file",
                    mime_type="text/plain",
                    file_name="report.txt",
                )
                context.services.attachment.store_upload_content(ticket.ticket_id, b"report-body")
                ready = context.services.attachment.complete_attachment(
                    attachment_id=attachment.attachment_id,
                    ticket_id=ticket.ticket_id,
                )

                view = context.services.attachment.build_attachment_object_view(ready)
                normalized = context.services.attachment.normalize_attachment_object_views(
                    [{"attachment_id": ready.attachment_id}]
                )

                self.assertEqual(view["attachment_id"], ready.attachment_id)
                self.assertEqual(view["file_name"], "report.txt")
                self.assertEqual(view["mime_type"], "text/plain")
                self.assertEqual(view["size_bytes"], len(b"report-body"))
                self.assertEqual(view["status"], "ready")
                self.assertEqual(normalized, [view])
            finally:
                context.engine.dispose()


if __name__ == "__main__":
    unittest.main()
