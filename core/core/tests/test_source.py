"""Source resolution — local dir passthrough, zip extraction, single-root descent."""
import os
import tempfile
import unittest
import zipfile

from core.source import resolve_source


class TestSource(unittest.TestCase):
    def test_local_dir_passthrough(self):
        d = tempfile.mkdtemp()
        r = resolve_source(d)
        self.assertEqual(r.root, d)
        r.cleanup()

    def test_zip_extracted_and_single_root_descended(self):
        tmp = tempfile.mkdtemp()
        zip_path = os.path.join(tmp, "app.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("app/main.py", "x = 1\n")
            zf.writestr("app/util.py", "y = 2\n")
        r = resolve_source(zip_path)
        try:
            self.assertTrue(os.path.isfile(os.path.join(r.root, "main.py")))  # descended into app/
        finally:
            r.cleanup()

    def test_missing_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_source("/no/such/path/here")


if __name__ == "__main__":
    unittest.main()
