from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta, timezone
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

    def test_attachment_service_prefers_presigned_download_url_when_backend_supports_it(self):
        class _FakePresignedStore:
            def __init__(self):
                self.objects = {}

            def put_bytes(self, object_key: str, content: bytes):
                self.objects[object_key] = bytes(content)
                return type("Stored", (), {"object_key": object_key, "size_bytes": len(content)})()

            def read_bytes(self, object_key: str) -> bytes:
                return self.objects[object_key]

            def delete_object(self, object_key: str) -> None:
                self.objects.pop(object_key, None)

            def generate_presigned_download_url(
                self,
                object_key: str,
                *,
                expires_in_seconds: int,
                file_name: str = "",
                mime_type: str = "",
            ) -> str:
                return (
                    f"https://object-store.example.com/{object_key}"
                    f"?expires={expires_in_seconds}&file_name={file_name}&mime_type={mime_type}"
                )

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                context.services.attachment._object_store = _FakePresignedStore()
                attachment, ticket = context.services.attachment.create_upload_ticket(
                    owner_type="thread",
                    owner_id="thr_presigned",
                    issuer_type="client",
                    issuer_ref="desktop-app",
                    kind="file",
                    mime_type="text/plain",
                    file_name="download.txt",
                )
                context.services.attachment.store_upload_content(ticket.ticket_id, b"presigned-content")
                context.services.attachment.complete_attachment(
                    attachment_id=attachment.attachment_id,
                    ticket_id=ticket.ticket_id,
                )

                download = context.services.attachment.create_download_ticket(
                    attachment_id=attachment.attachment_id,
                    issuer_type="client",
                    issuer_ref="desktop-app",
                    fallback_download_url="http://127.0.0.1:8000/client/attachments/content/demo?ticket_id=",
                )

                self.assertEqual(download["download_strategy"], "presigned")
                self.assertIn("https://object-store.example.com/", download["download_url"])
                self.assertEqual(
                    download["fallback_download_url"],
                    "http://127.0.0.1:8000/client/attachments/content/demo?ticket_id=",
                )
            finally:
                context.engine.dispose()

    def test_screenshot_attachment_defaults_to_ephemeral_and_is_cleaned_after_expiry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                attachment, ticket = context.services.attachment.create_upload_ticket(
                    owner_type="operation",
                    owner_id="op_screenshot_1",
                    issuer_type="agent",
                    issuer_ref="desktop-main-agent",
                    kind="screenshot",
                    mime_type="image/png",
                    file_name="capture.png",
                )
                self.assertEqual(attachment.lifecycle_policy, "ephemeral")
                self.assertTrue(attachment.expires_at)

                context.services.attachment.store_upload_content(ticket.ticket_id, b"png-bytes")
                ready = context.services.attachment.complete_attachment(
                    attachment_id=attachment.attachment_id,
                    ticket_id=ticket.ticket_id,
                )
                expires_at = ready.expires_at
                self.assertTrue(expires_at)

                cleanup_time = (
                    context.services.attachment._read_iso_datetime(expires_at)
                    .astimezone(timezone.utc)
                    + timedelta(seconds=1)
                )
                result = context.services.attachment.cleanup_expired_resources(now=cleanup_time)
                expired = context.services.attachment.get_by_attachment_id(attachment.attachment_id)

                self.assertGreaterEqual(result["expired_attachments"], 1)
                self.assertGreaterEqual(result["deleted_objects"], 1)
                self.assertEqual(expired.status, "expired")
                with self.assertRaises(ValueError):
                    context.services.attachment.read_attachment_bytes(attachment.attachment_id)
            finally:
                context.engine.dispose()

    def test_retained_attachment_does_not_get_default_expiry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context = bootstrap_core_domain(
                database_url=TEST_DATABASE_URL,
                run_migrations=True,
                attachment_storage_root=Path(tmp_dir),
            )
            try:
                attachment, _ticket = context.services.attachment.create_upload_ticket(
                    owner_type="thread",
                    owner_id="thr_retained",
                    issuer_type="client",
                    issuer_ref="desktop-app",
                    kind="file",
                    mime_type="text/plain",
                    file_name="retained.txt",
                    lifecycle_policy="retained",
                )
                self.assertEqual(attachment.lifecycle_policy, "retained")
                self.assertFalse(attachment.expires_at)
            finally:
                context.engine.dispose()


if __name__ == "__main__":
    unittest.main()
