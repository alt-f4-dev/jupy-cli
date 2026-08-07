#!/usr/bin/env python3
"""Self-updater for the jupy/jupip/jupyup CLI installation.

jupyup checks the latest GitHub release of alt-f4-dev/jupy-cli, downloads the
release source archive, validates its layout and version, and atomically replaces
the installed CLI files. Project-local Julia/Python environments are never
modified.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import urllib.error
import urllib.request
import zipfile

DEFAULT_REPOSITORY = "alt-f4-dev/jupy-cli"
DEFAULT_API_VERSION = "2026-03-10"
PROGRAM = "jupyup"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


class JupyUpdateError(RuntimeError):
    """Expected user-facing updater failure."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: Tuple[object, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        text = value.strip()
        if text.startswith("v"):
            text = text[1:]

        match = re.fullmatch(
            r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
            text,
        )
        if not match:
            raise JupyUpdateError(f"invalid semantic version: {value!r}")

        prerelease: List[object] = []
        if match.group(4):
            for identifier in match.group(4).split("."):
                prerelease.append(int(identifier) if identifier.isdigit() else identifier)

        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tuple(prerelease),
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if not self.prerelease:
            return base
        return base + "-" + ".".join(str(item) for item in self.prerelease)

    def _compare_prerelease(self, other: "SemVer") -> int:
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1

        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, str):
                return -1
            if isinstance(left, str) and isinstance(right, int):
                return 1
            return -1 if left < right else 1

        if len(self.prerelease) == len(other.prerelease):
            return 0
        return -1 if len(self.prerelease) < len(other.prerelease) else 1

    def _cmp(self, other: "SemVer") -> int:
        left_core = (self.major, self.minor, self.patch)
        right_core = (other.major, other.minor, other.patch)
        if left_core != right_core:
            return -1 if left_core < right_core else 1
        return self._compare_prerelease(other)

    def __lt__(self, other: "SemVer") -> bool:
        return self._cmp(other) < 0

    def __le__(self, other: "SemVer") -> bool:
        return self._cmp(other) <= 0

    def __gt__(self, other: "SemVer") -> bool:
        return self._cmp(other) > 0

    def __ge__(self, other: "SemVer") -> bool:
        return self._cmp(other) >= 0


@dataclass(frozen=True)
class ReleaseInfo:
    version: SemVer
    tag: str
    archive_url: str


@dataclass
class Backup:
    target: Path
    existed: bool
    data: bytes = b""
    mode: Optional[int] = None


def log(message: str) -> None:
    print(f"{PROGRAM}: {message}")


def error(message: str) -> None:
    print(f"{PROGRAM}: {message}", file=sys.stderr)


def repository() -> str:
    return os.environ.get("JUPY_GITHUB_REPOSITORY", DEFAULT_REPOSITORY).strip()


def api_version() -> str:
    return os.environ.get("JUPY_GITHUB_API_VERSION", DEFAULT_API_VERSION).strip()


def install_root() -> Path:
    configured = os.environ.get("JUPY_INSTALL_ROOT")
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured))).resolve()

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise JupyUpdateError("LOCALAPPDATA is not set; set JUPY_INSTALL_ROOT explicitly")
        return (Path(local_app_data) / "Jupy").resolve()

    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return (Path(os.path.expandvars(os.path.expanduser(data_home))) / "jupy").resolve()
    return (Path.home() / ".local" / "share" / "jupy").resolve()


def external_bin_dir(root: Path) -> Path:
    if os.name == "nt":
        return root / "bin"

    configured = os.environ.get("JUPY_BIN_DIR")
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
    return (Path.home() / ".local" / "bin").resolve()


def read_version_file(path: Path) -> SemVer:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise JupyUpdateError(f"could not read version file {path}: {exc}") from exc
    return SemVer.parse(text)


def installed_version(root: Path) -> SemVer:
    version_path = root / "VERSION"
    if version_path.is_file():
        return read_version_file(version_path)

    # Backward-compatible fallback for installations created before VERSION was
    # copied into the install root.
    core = root / "core" / "jupy_core.py"
    if not core.is_file():
        raise JupyUpdateError(
            f"jupy does not appear to be installed at {root}; reinstall it before using jupyup"
        )

    try:
        source = core.read_text(encoding="utf-8")
    except OSError as exc:
        raise JupyUpdateError(f"could not read installed core {core}: {exc}") from exc

    match = re.search(r'^TOOL_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not match:
        raise JupyUpdateError(
            f"could not determine installed jupy version; missing {version_path} and TOOL_VERSION"
        )
    return SemVer.parse(match.group(1))


def github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jupyup",
    }
    version = api_version()
    if version:
        headers["X-GitHub-Api-Version"] = version
    return headers


def fetch_latest_release(repo: str) -> ReleaseInfo:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers=github_headers())

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise JupyUpdateError(
                f"no published GitHub release was found for {repo}; create a release first"
            ) from exc
        raise JupyUpdateError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise JupyUpdateError(f"could not reach GitHub: {exc.reason}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise JupyUpdateError(f"could not read GitHub release metadata: {exc}") from exc

    tag = str(payload.get("tag_name", "")).strip()
    archive_url = str(payload.get("zipball_url", "")).strip()
    if not tag or not archive_url:
        raise JupyUpdateError("latest GitHub release metadata is missing tag_name or zipball_url")

    return ReleaseInfo(version=SemVer.parse(tag), tag=tag, archive_url=archive_url)


def download_archive(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=github_headers())
    total = 0

    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise JupyUpdateError(
                        f"release archive exceeds the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MiB safety limit"
                    )
                handle.write(block)
    except urllib.error.HTTPError as exc:
        raise JupyUpdateError(f"release download failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise JupyUpdateError(f"release download failed: {exc.reason}") from exc
    except OSError as exc:
        raise JupyUpdateError(f"could not save release archive: {exc}") from exc


def safe_extract_zip(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise JupyUpdateError(
                        f"release archive contains an unsafe path: {member.filename!r}"
                    )

                target = destination.joinpath(*relative.parts)
                resolved = target.resolve()
                destination_resolved = destination.resolve()
                try:
                    resolved.relative_to(destination_resolved)
                except ValueError as exc:
                    raise JupyUpdateError(
                        f"release archive path escapes extraction directory: {member.filename!r}"
                    ) from exc

            zipped.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise JupyUpdateError("downloaded release archive is not a valid ZIP file") from exc
    except OSError as exc:
        raise JupyUpdateError(f"could not extract release archive: {exc}") from exc


def required_release_files(platform_name: Optional[str] = None) -> Tuple[str, ...]:
    platform_name = platform_name or os.name
    common = (
        "VERSION",
        "core/jupy_core.py",
        "core/jupy_update.py",
    )
    if platform_name == "nt":
        return common + (
            "bin/jupy.ps1",
            "bin/jupy.cmd",
            "bin/jupip.ps1",
            "bin/jupip.cmd",
            "bin/jupyup.ps1",
            "bin/jupyup.cmd",
        )
    return common + (
        "bin/jupy",
        "bin/jupip",
        "bin/jupyup",
    )


def locate_release_root(extracted: Path, platform_name: Optional[str] = None) -> Path:
    required = required_release_files(platform_name)
    candidates: List[Path] = []

    if all((extracted / relative).is_file() for relative in required):
        candidates.append(extracted)

    for version_file in extracted.rglob("VERSION"):
        candidate = version_file.parent
        if all((candidate / relative).is_file() for relative in required):
            candidates.append(candidate)

    unique: List[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)

    if len(unique) != 1:
        if not unique:
            raise JupyUpdateError("release archive does not contain the expected jupy-cli layout")
        raise JupyUpdateError("release archive contains multiple possible jupy-cli roots")
    return unique[0]


def validate_release_tree(source_root: Path, release: ReleaseInfo) -> None:
    for relative in required_release_files():
        path = source_root / relative
        if not path.is_file():
            raise JupyUpdateError(f"release is missing required file: {relative}")

    source_version = read_version_file(source_root / "VERSION")
    if source_version != release.version:
        raise JupyUpdateError(
            f"release tag {release.tag!r} does not match VERSION {source_version}"
        )

    for relative in ("core/jupy_core.py", "core/jupy_update.py"):
        path = source_root / relative
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, SyntaxError) as exc:
            raise JupyUpdateError(f"release validation failed for {relative}: {exc}") from exc


def install_manifest(
    source_root: Path,
    root: Path,
    bin_dir: Path,
    platform_name: Optional[str] = None,
) -> List[Tuple[Path, Path, bool]]:
    platform_name = platform_name or os.name
    manifest: List[Tuple[Path, Path, bool]] = [
        (source_root / "VERSION", root / "VERSION", False),
        (source_root / "core" / "jupy_core.py", root / "core" / "jupy_core.py", False),
        (source_root / "core" / "jupy_update.py", root / "core" / "jupy_update.py", False),
    ]

    if platform_name == "nt":
        for name in ("jupy.ps1", "jupy.cmd", "jupip.ps1", "jupip.cmd", "jupyup.ps1", "jupyup.cmd"):
            manifest.append((source_root / "bin" / name, root / "bin" / name, False))
        return manifest

    for name in ("jupy", "jupip", "jupyup"):
        source = source_root / "bin" / name
        installed = root / "bin" / name
        manifest.append((source, installed, True))

        external = bin_dir / name
        if external.is_symlink():
            # Preserve installer-created symlinks. Updating root/bin/<name> is
            # sufficient because the symlink continues to point at the new file.
            continue
        manifest.append((source, external, True))

    return manifest


def backup_target(target: Path) -> Backup:
    if target.is_symlink():
        raise JupyUpdateError(f"refusing to replace unexpected symlink: {target}")
    if not target.exists():
        return Backup(target=target, existed=False)
    if not target.is_file():
        raise JupyUpdateError(f"refusing to replace non-file path: {target}")

    try:
        return Backup(
            target=target,
            existed=True,
            data=target.read_bytes(),
            mode=stat.S_IMODE(target.stat().st_mode),
        )
    except OSError as exc:
        raise JupyUpdateError(f"could not back up {target}: {exc}") from exc


def atomic_copy(source: Path, target: Path, executable: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.jupyup.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())

        temporary = Path(temporary_name)
        if executable and os.name != "nt":
            temporary.chmod(0o755)
        os.replace(temporary, target)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise JupyUpdateError(f"could not install {target}: {exc}") from exc


def restore_backup(backup: Backup) -> None:
    target = backup.target
    if not backup.existed:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.rollback.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(backup.data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = Path(temporary_name)
        if backup.mode is not None and os.name != "nt":
            temporary.chmod(backup.mode)
        os.replace(temporary, target)
    except OSError:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def apply_update(source_root: Path, root: Path, bin_dir: Path) -> None:
    manifest = install_manifest(source_root, root, bin_dir)
    backups: List[Backup] = []

    try:
        for source, target, executable in manifest:
            if not source.is_file():
                raise JupyUpdateError(f"release source file is missing: {source}")
            backup = backup_target(target)
            backups.append(backup)
            atomic_copy(source, target, executable)
    except Exception:
        for backup in reversed(backups):
            restore_backup(backup)
        raise


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Update the installed jupy/jupip/jupyup CLI from the latest GitHub release.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check for an update without installing it",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="reinstall the latest release even when the installed version matches",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the installed jupy CLI version and exit",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.version_info < (3, 8):
        error("Python 3.8 or newer is required")
        return 2

    arguments = parse_arguments(argv)

    try:
        root = install_root()
        local = installed_version(root)

        if arguments.version:
            print(local)
            return 0

        repo = repository()
        release = fetch_latest_release(repo)

        log(f"installed version: {local}")
        log(f"latest version:    {release.version}")

        if release.version < local:
            log("installed version is newer than the latest published release; no update applied")
            return 0

        if release.version == local and not arguments.force:
            log("already up to date")
            return 0

        if arguments.check:
            if release.version == local:
                log("installed version matches the latest release")
            else:
                log(f"update available: {local} -> {release.version}")
            return 0

        bin_dir = external_bin_dir(root)
        with tempfile.TemporaryDirectory(prefix="jupyup-") as temporary_directory:
            temporary = Path(temporary_directory)
            archive = temporary / "release.zip"
            extracted = temporary / "release"
            extracted.mkdir()

            log(f"downloading {repo} release {release.tag}")
            download_archive(release.archive_url, archive)
            safe_extract_zip(archive, extracted)
            source_root = locate_release_root(extracted)
            validate_release_tree(source_root, release)
            apply_update(source_root, root, bin_dir)

        installed = installed_version(root)
        if installed != release.version:
            raise JupyUpdateError(
                f"post-update version check failed: expected {release.version}, found {installed}"
            )

        log(f"updated jupy {local} -> {installed}")
        return 0

    except JupyUpdateError as exc:
        error(str(exc))
        return 1
    except KeyboardInterrupt:
        error("update interrupted")
        return 130
    except OSError as exc:
        error(f"operating-system error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
