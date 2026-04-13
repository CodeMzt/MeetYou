import tempfile
import unittest
from pathlib import Path

from core.exceptions import ConfigError
from core.storage.object_store import LocalObjectStore, S3CompatibleObjectStore, build_object_store, resolve_object_store_settings


class _FakeConfig:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _Body:
    def read(self):
        return b"hello-s3"


class _FakeS3Client:
    def __init__(self):
        self.put_calls = []
        self.delete_calls = []
        self.presign_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)

    def get_object(self, **kwargs):
        return {"Body": _Body()}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)

    def generate_presigned_url(self, operation_name, *, Params, ExpiresIn):
        self.presign_calls.append(
            {
                "operation_name": operation_name,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
            }
        )
        return "https://object-store.example.com/presigned/demo"


class ObjectStoreTests(unittest.TestCase):
    def test_resolve_local_object_store_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = _FakeConfig({
                "object_store_backend": "filesystem",
                "attachment_storage_root": str(Path(tmp_dir) / "attachments"),
            })
            settings = resolve_object_store_settings(config)
            self.assertEqual(settings.backend, "filesystem")
            self.assertEqual(settings.root, Path(tmp_dir) / "attachments")

    def test_build_local_object_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = build_object_store(_FakeConfig({"attachment_storage_root": tmp_dir}))
            self.assertIsInstance(store, LocalObjectStore)
            written = store.put_bytes("attachments/test.txt", b"hello")
            self.assertEqual(written.size_bytes, 5)
            self.assertEqual(store.resolve_path("attachments/test.txt").read_bytes(), b"hello")
            self.assertEqual(
                store.generate_presigned_download_url(
                    "attachments/test.txt",
                    expires_in_seconds=300,
                    file_name="test.txt",
                    mime_type="text/plain",
                ),
                "",
            )
            store.delete_object("attachments/test.txt")
            with self.assertRaises(FileNotFoundError):
                store.resolve_path("attachments/test.txt")

    def test_unsupported_object_store_backend_raises(self):
        with self.assertRaises(ConfigError):
            build_object_store(_FakeConfig({"object_store_backend": "unknown_backend"}))

    def test_s3_compatible_object_store_uses_client_interface(self):
        client = _FakeS3Client()
        store = S3CompatibleObjectStore(bucket="demo", client=client)
        written = store.put_bytes("attachments/demo.txt", b"hello-s3")
        self.assertEqual(written.object_key, "attachments/demo.txt")
        self.assertEqual(store.read_bytes("attachments/demo.txt"), b"hello-s3")
        self.assertEqual(client.put_calls[0]["Bucket"], "demo")
        self.assertEqual(
            store.generate_presigned_download_url(
                "attachments/demo.txt",
                expires_in_seconds=300,
                file_name="demo.txt",
                mime_type="text/plain",
            ),
            "https://object-store.example.com/presigned/demo",
        )
        store.delete_object("attachments/demo.txt")
        self.assertEqual(client.delete_calls[0]["Key"], "attachments/demo.txt")
        self.assertEqual(client.presign_calls[0]["operation_name"], "get_object")
        self.assertEqual(client.presign_calls[0]["Params"]["ResponseContentType"], "text/plain")
        self.assertEqual(
            client.presign_calls[0]["Params"]["ResponseContentDisposition"],
            'attachment; filename="demo.txt"; filename*=UTF-8\'\'demo.txt',
        )

    def test_s3_compatible_presigned_url_encodes_unicode_file_name(self):
        client = _FakeS3Client()
        store = S3CompatibleObjectStore(bucket="attachments", client=client)

        store.generate_presigned_download_url(
            "attachments/unicode.png",
            expires_in_seconds=300,
            file_name="大白LOGO.png",
            mime_type="image/png",
        )

        disposition = client.presign_calls[0]["Params"]["ResponseContentDisposition"]
        self.assertIn('filename="LOGO.png"', disposition)
        self.assertIn("filename*=UTF-8''%E5%A4%A7%E7%99%BDLOGO.png", disposition)


if __name__ == "__main__":
    unittest.main()
