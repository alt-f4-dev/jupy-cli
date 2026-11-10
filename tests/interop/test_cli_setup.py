"""Validate explicit interop provisioning without modifying real environments."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("jupy_core_interop", ROOT / "core" / "jupy_core.py")
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class SetupTests(unittest.TestCase):
    def test_pip_setup_vendors_sources_and_installs_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").write_text("[deps]\n", encoding="utf-8")
            (root / ".venv").mkdir()
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                return type("Result", (), {"returncode": 0})()
            with patch.object(core, "run_checked", side_effect=run), \
                 patch.object(core, "sync_requirements") as sync, \
                 patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                core.install_interop(root, "/fake/julia", root / ".venv" / "python", "jupy")
            self.assertTrue((root / ".jupy-interop" / "python" / "jupy" / "runtime.py").is_file())
            self.assertTrue((root / ".jupy-interop" / "julia" / "Jupy" / "src" / "Jupy.jl").is_file())
            self.assertEqual(calls[0][:4], [str(root / ".venv" / "python"), "-m", "pip", "install"])
            self.assertEqual(calls[1][0], "/fake/julia")
            sync.assert_called_once()

    def test_uv_setup_never_invokes_pip_or_freeze(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").touch()
            (root / ".venv").mkdir()
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                return type("Result", (), {"returncode": 0})()
            with patch.object(core, "run_checked", side_effect=run), \
                 patch.object(core, "find_uv", return_value="uv"), \
                 patch.object(core, "sync_requirements") as sync, \
                 patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                core.install_interop(root, "julia", root / ".venv" / "python", "juuv")
            self.assertEqual(calls[0][:3], ["uv", "add", "--editable"])
            self.assertEqual(calls[1][0], "julia")
            sync.assert_not_called()

    def test_missing_sources_refuses_before_project_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": folder}):
                with self.assertRaisesRegex(core.JupyError, "unavailable"):
                    core.install_interop(root, "julia", root / "python", "juuv")
            self.assertFalse((root / ".jupy-interop").exists())


    def test_idempotent_setup_preserves_vendored_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Project.toml").touch()
            (root / ".venv").mkdir()
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                return type("Result", (), {"returncode": 0})()
            with patch.object(core, "run_checked", side_effect=run), \
                 patch.object(core, "sync_requirements"), \
                 patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                core.install_interop(root, "julia", root / ".venv" / "python", "jupy")
                source = root / ".jupy-interop" / "python" / "jupy" / "runtime.py"
                first = source.read_bytes()
                core.install_interop(root, "julia", root / ".venv" / "python", "jupy")
                self.assertEqual(source.read_bytes(), first)
                self.assertEqual(len(calls), 4)
                source.write_text("local edits", encoding="utf-8")
                with self.assertRaisesRegex(core.JupyError, "vendored interop source differs"):
                    core.install_interop(root, "julia", root / ".venv" / "python", "jupy")
                self.assertEqual(len(calls), 4)

    def test_rejects_incompatible_julia_manifest_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Manifest.toml").write_text(
                '[[deps.PythonCall]]\nversion = "0.9.36"\n',
                encoding="utf-8",
            )
            with patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                with self.assertRaisesRegex(core.JupyError, "requires 0.9.37"):
                    core.install_interop(root, "julia", root / "python", "jupy")
            self.assertFalse((root / ".jupy-interop").exists())

    def test_rejects_pip_setup_for_uv_owned_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            venv = root / ".venv"
            venv.mkdir()
            (venv / ".jupy-backend").write_text("uv\n")
            with patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                with self.assertRaisesRegex(core.JupyError, "uv-managed"):
                    core.install_interop(root, "julia", venv / "python", "jupy")
            self.assertFalse((root / ".jupy-interop").exists())

    def test_vendored_file_integrity_preflight_catches_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".venv").mkdir()
            with patch.object(core, "run_checked") as run, \
                 patch.object(core, "sync_requirements"), \
                 patch.dict(core.os.environ, {"JUPY_INTEROP_SOURCE": str(ROOT)}):
                run.return_value.returncode = 0
                core.install_interop(root, "julia", root / ".venv" / "python", "jupy")
                (root / ".jupy-interop" / "julia" / "Jupy" / "src" / "Jupy.jl").unlink()
                with self.assertRaisesRegex(core.JupyError, "vendored interop source differs"):
                    core.install_interop(root, "julia", root / ".venv" / "python", "jupy")
                self.assertEqual(run.call_count, 2)

if __name__ == "__main__":
    unittest.main()
