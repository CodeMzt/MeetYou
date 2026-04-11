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

    def test_unsupported_object_store_backend_raises(self):
        with self.assertRaises(ConfigError):
            build_object_store(_FakeConfig({"object_store_backend": "unknown_backend"}))

    def test_s3_compatible_object_store_uses_client_interface(self):
        class _Body:
            def read(self):
                return b"hello-s3"

        class _FakeS3Client:
            def __init__(self):
                self.put_calls = []

            def put_object(self, **kwargs):
                self.put_calls.append(kwargs)

            def get_object(self, **kwargs):
                return {"Body": _Body()}

        client = _FakeS3Client()
        store = S3CompatibleObjectStore(bucket="demo", client=client)
        written = store.put_bytes("attachments/demo.txt", b"hello-s3")
        self.assertEqual(written.object_key, "attachments/demo.txt")
        self.assertEqual(store.read_bytes("attachments/demo.txt"), b"hello-s3")
        self.assertEqual(client.put_calls[0]["Bucket"], "demo")


if __name__ == "__main__":
    unittest.main()
