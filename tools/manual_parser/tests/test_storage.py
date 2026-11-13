from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from manual_parser.storage import JobStore


class StorageTests(unittest.TestCase):
    def test_upload_is_streamed_and_keeps_original_name(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            job = store.create_from_stream("公司手册.DOCX", io.BytesIO(b"0123456789"), 10)
            self.assertEqual("公司手册.DOCX", job["filename"])
            self.assertEqual(b"0123456789", (store.job_dir(job["id"]) / "source.docx").read_bytes())

    def test_incomplete_upload_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            with self.assertRaises(ValueError):
                store.create_from_stream("broken.pdf", io.BytesIO(b"short"), 20)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_content_hash_cache_and_interrupted_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            first = store.create("first.pdf", b"same manual")
            self.assertEqual(64, len(first["content_sha256"]))
            store.update(first["id"], pipeline_signature="pipeline-v1", status="completed")
            store.save_result(first["id"], {"markdown": "done"})
            duplicate = store.create("duplicate.pdf", b"same manual")
            reusable = store.find_reusable(duplicate["content_sha256"], "pipeline-v1", exclude_id=duplicate["id"])
            self.assertEqual(first["id"], reusable["id"])

            running = store.create("running.pdf", b"other")
            store.update(running["id"], status="running")
            self.assertEqual(2, store.recover_interrupted())  # duplicate is queued and the other task is running
            self.assertEqual("interrupted", store.status(running["id"])["status"])

    def test_delete_removes_job_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            job = store.create("manual.pdf", b"content")
            store.delete(job["id"])
            self.assertFalse(store.job_dir(job["id"]).exists())

    def test_export_package_rewrites_live_region_links(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            job = store.create("manual.pdf", b"pdf")
            job_dir = store.job_dir(job["id"])
            (job_dir / "regions").mkdir()
            (job_dir / "regions" / "figure.webp").write_bytes(b"image")
            store.save_result(
                job["id"],
                {"markdown": f"![图](/api/jobs/{job['id']}/regions/figure.webp)", "blocks": []},
            )
            package = store.export_package(job["id"])
            with zipfile.ZipFile(package) as archive:
                self.assertIn("regions/figure.webp", archive.namelist())
                self.assertIn("![图](regions/figure.webp)", archive.read("result.md").decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
