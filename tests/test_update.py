from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jupy_update", ROOT / "core" / "jupy_update.py")
assert SPEC is not None and SPEC.loader is not None
update = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update
SPEC.loader.exec_module(update)


class SemVerTests(unittest.TestCase):
    def test_basic_ordering(self):
        self.assertLess(update.SemVer.parse("0.0.1"), update.SemVer.parse("0.0.2"))
        self.assertLess(update.SemVer.parse("1.9.9"), update.SemVer.parse("2.0.0"))
        self.assertEqual(update.SemVer.parse("v1.2.3"), update.SemVer.parse("1.2.3"))

    def test_prerelease_ordering(self):
        self.assertLess(update.SemVer.parse("1.0.0-alpha"), update.SemVer.parse("1.0.0"))
        self.assertLess(update.SemVer.parse("1.0.0-alpha.1"), update.SemVer.parse("1.0.0-alpha.beta"))


class LayoutTests(unittest.TestCase):
    def make_release_tree(self, root: Path, platform_name: str = "posix") -> Path:
        source = root / "alt-f4-dev-jupy-cli-deadbeef"
        for relative in update.required_release_files(platform_name):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == "VERSION":
                path.write_text("1.2.3\n", encoding="utf-8")
            elif relative.endswith(".py"):
                path.write_text("VALUE = 1\n", encoding="utf-8")
            else:
                path.write_text("launcher\n", encoding="utf-8")
        return source

    def test_locate_release_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            extracted = Path(temporary)
            source = self.make_release_tree(extracted)
            self.assertEqual(update.locate_release_root(extracted, "posix"), source.resolve())

    def test_validate_release_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.make_release_tree(Path(temporary))
            release = update.ReleaseInfo(
                version=update.SemVer.parse("1.2.3"),
                tag="v1.2.3",
                archive_url="https://example.invalid/release.zip",
            )
            update.validate_release_tree(source, release)

    def test_posix_manifest_preserves_external_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_release_tree(base / "source")
            root = base / "installed"
            bin_dir = base / "external-bin"
            (root / "bin").mkdir(parents=True)
            bin_dir.mkdir()

            for name in ("jupy", "jupip", "jupyup"):
                target = root / "bin" / name
                target.write_text("old\n", encoding="utf-8")
                (bin_dir / name).symlink_to(target)

            manifest = update.install_manifest(source, root, bin_dir, "posix")
            targets = [target for _, target, _ in manifest]

            self.assertIn(root / "bin" / "jupy", targets)
            self.assertNotIn(bin_dir / "jupy", targets)
            self.assertNotIn(bin_dir / "jupip", targets)
            self.assertNotIn(bin_dir / "jupyup", targets)


    def test_windows_manifest_contains_all_windows_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_release_tree(base / "source", "nt")
            root = base / "installed"
            manifest = update.install_manifest(source, root, root / "bin", "nt")
            targets = {target.relative_to(root).as_posix() for _, target, _ in manifest}
            self.assertEqual(
                targets,
                {
                    "VERSION",
                    "core/jupy_core.py",
                    "core/jupy_update.py",
                    "bin/jupy.ps1",
                    "bin/jupy.cmd",
                    "bin/jupip.ps1",
                    "bin/jupip.cmd",
                    "bin/jupyup.ps1",
                    "bin/jupyup.cmd",
                },
            )

    def test_apply_update_to_regular_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_release_tree(base / "source")
            root = base / "installed"
            bin_dir = base / "external-bin"
            (root / "core").mkdir(parents=True)
            (root / "bin").mkdir(parents=True)
            bin_dir.mkdir()

            (root / "VERSION").write_text("1.2.2\n", encoding="utf-8")
            (root / "core" / "jupy_core.py").write_text("OLD = 1\n", encoding="utf-8")
            (root / "core" / "jupy_update.py").write_text("OLD = 1\n", encoding="utf-8")
            for name in ("jupy", "jupip", "jupyup"):
                (root / "bin" / name).write_text("old\n", encoding="utf-8")
                (bin_dir / name).write_text("old\n", encoding="utf-8")

            update.apply_update(source, root, bin_dir)

            self.assertEqual((root / "VERSION").read_text(encoding="utf-8"), "1.2.3\n")
            self.assertEqual((bin_dir / "jupyup").read_text(encoding="utf-8"), "launcher\n")


if __name__ == "__main__":
    unittest.main()
