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


if __name__ == "__main__":
    unittest.main()
