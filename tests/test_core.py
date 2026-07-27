from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

CORE = Path(__file__).resolve().parents[1] / "core" / "jupy_core.py"
SPEC = importlib.util.spec_from_file_location("jupy_core", CORE)
assert SPEC and SPEC.loader
jupy_core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jupy_core)


class CoreTests(unittest.TestCase):
    def test_project_discovery_uses_nearest_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "outer"
            nested = project / "a" / "b"
            nested.mkdir(parents=True)
            (project / "Project.toml").write_text("[deps]\n", encoding="utf-8")
            self.assertEqual(jupy_core.find_project_root(nested), project.resolve())

    def test_project_discovery_falls_back_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            start = Path(directory) / "new"
            start.mkdir()
            self.assertEqual(jupy_core.find_project_root(start), start.resolve())

    def test_julia_project_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Project.toml").touch()
            (root / "JuliaProject.toml").touch()
            self.assertEqual(jupy_core.project_file(root), root / "JuliaProject.toml")

    def test_pythoncall_must_be_in_deps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "Project.toml"
            project.write_text(
                "[compat]\nPythonCall = \"0.9\"\n\n[deps]\nExample = \"x\"\n",
                encoding="utf-8",
            )
            self.assertFalse(jupy_core.project_has_pythoncall(project))
            project.write_text(
                "[deps]\nPythonCall = \"6099a3de-0909-46bc-9c72-19260b30ff38\"\n",
                encoding="utf-8",
            )
            self.assertTrue(jupy_core.project_has_pythoncall(project))

    def test_support_files_are_created_but_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jupy_core.ensure_support_files(root, "test")
            self.assertEqual((root / ".gitignore").read_text(), jupy_core.GITIGNORE_CONTENT)
            self.assertEqual((root / "requirements.txt").read_text(), "")
            (root / ".gitignore").write_text("custom\n", encoding="utf-8")
            jupy_core.ensure_support_files(root, "test")
            self.assertEqual((root / ".gitignore").read_text(), "custom\n")

    def test_platform_virtual_environment_paths(self) -> None:
        root = Path("project")
        self.assertEqual(
            jupy_core.venv_python_path(root, "posix"),
            root / ".venv" / "bin" / "python",
        )
        self.assertEqual(
            jupy_core.venv_python_path(root, "nt"),
            root / ".venv" / "Scripts" / "python.exe",
        )

    def test_mutating_pip_commands(self) -> None:
        self.assertTrue(jupy_core.pip_command_mutates_environment(["install", "numpy"]))
        self.assertTrue(jupy_core.pip_command_mutates_environment(["uninstall", "numpy"]))
        self.assertFalse(jupy_core.pip_command_mutates_environment(["list"]))

    def test_fingerprint_changes_with_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "Project.toml"
            project.write_text("[deps]\n", encoding="utf-8")
            first = jupy_core.julia_environment_fingerprint(root)
            project.write_text("[deps]\nExample = \"x\"\n", encoding="utf-8")
            second = jupy_core.julia_environment_fingerprint(root)
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
