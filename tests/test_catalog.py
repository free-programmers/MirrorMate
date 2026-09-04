import json
import os
import tempfile
import unittest
from pathlib import Path

from mirrormate.catalog import (
    builtin_catalog_path,
    load_catalogs,
    mutate_custom_catalog,
    normalize_entry,
    parse_catalog,
    read_catalog,
    remove_custom_mirror,
)
from mirrormate.errors import CatalogError
from mirrormate.platform import UserContext


class CatalogTests(unittest.TestCase):
    def test_builtin_catalog_contains_only_official_sources(self):
        mirrors = read_catalog(builtin_catalog_path(), "builtin")
        self.assertEqual({item.source for item in mirrors}, {"builtin"})
        self.assertEqual({item.type for item in mirrors}, {"apt", "python", "npm", "go", "docker"})
        self.assertTrue(all("official" in item.name.lower() or item.default for item in mirrors))

    def test_current_legacy_catalog_is_importable(self):
        raw = json.loads(Path("mirros/mirrors.json").read_text(encoding="utf-8"))
        mirrors = parse_catalog(raw)
        self.assertEqual(len(mirrors), len(raw))
        self.assertEqual(len({item.id for item in mirrors}), len(mirrors))
        apt = next(item for item in mirrors if item.type == "apt")
        self.assertEqual(apt.distro, "ubuntu")
        self.assertIsNotNone(apt.archive_url)

    def test_canonical_catalog_rejects_duplicate_ids(self):
        entry = {"id": "same-id", "type": "python", "name": "One", "url": "https://one.example"}
        with self.assertRaises(CatalogError):
            parse_catalog({"schema_version": 1, "mirrors": [entry, entry]})

    def test_mutate_and_remove_user_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            user = UserContext("tester", os.getuid(), os.getgid(), home)
            mirror = normalize_entry(
                {"id": "custom-pypi", "type": "python", "name": "Custom", "url": "https://pypi.example/simple"}
            )
            path = mutate_custom_catalog([mirror], user=user)
            self.assertTrue(path.is_file())
            loaded = load_catalogs(user)
            self.assertIn("custom-pypi", {item.id for item in loaded})
            with self.assertRaises(CatalogError):
                mutate_custom_catalog([mirror], user=user)
            remove_custom_mirror("custom-pypi", user=user)
            self.assertNotIn("custom-pypi", {item.id for item in load_catalogs(user)})

    def test_builtin_ids_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            user = UserContext("tester", os.getuid(), os.getgid(), Path(temporary))
            mirror = normalize_entry(
                {"id": "pypi-official", "type": "python", "name": "Fake", "url": "https://fake.example"}
            )
            with self.assertRaises(CatalogError):
                mutate_custom_catalog([mirror], user=user, replace=True)

    def test_http_docker_mirror_must_be_marked_insecure(self):
        entry = {"id": "docker-http", "type": "docker", "name": "HTTP", "url": "http://docker.example"}
        with self.assertRaises(CatalogError):
            normalize_entry(entry)
        entry["insecure"] = True
        self.assertTrue(normalize_entry(entry).insecure)

    def test_canonical_entry_rejects_unknown_fields(self):
        entry = {
            "id": "custom-pypi",
            "type": "python",
            "name": "Custom",
            "url": "https://pypi.example/simple",
            "urll": "https://typo.example",
        }
        with self.assertRaises(CatalogError):
            normalize_entry(entry)


if __name__ == "__main__":
    unittest.main()
