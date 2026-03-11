#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path


WINDOWS_REQUIRED_SUFFIXES = (
    "openaihub.exe",
    "openai_codex_login_helper.mjs",
    "openclaw_restart_gateway.ps1",
    "openclaw_restart_gateway.sh",
    "bundled_runtime/oauth/openai-codex.js",
)

MACOS_REQUIRED_SUFFIXES = (
    "openaihub",
    "OAH",
    "openaihub-bin",
    "openai_codex_login_helper.mjs",
    "openclaw_restart_gateway.ps1",
    "openclaw_restart_gateway.sh",
    "bundled_runtime/oauth/openai-codex.js",
)

MACOS_REQUIRED_SYMLINK_SUFFIX = "_internal/Python"
MACOS_REQUIRED_SYMLINK_TARGET = "Python.framework/Versions/3.12/Python"
WINDOWS_RUNTIME_REQUIRED_PATHS = (
    "openaihub.exe",
    "_internal/openai_codex_login_helper.mjs",
    "_internal/openclaw_restart_gateway.ps1",
    "_internal/openclaw_restart_gateway.sh",
    "_internal/bundled_runtime/oauth/openai-codex.js",
)
MACOS_RUNTIME_REQUIRED_PATHS = (
    "openaihub",
    "OAH",
    "openaihub-bin",
    "_internal/openai_codex_login_helper.mjs",
    "_internal/openclaw_restart_gateway.ps1",
    "_internal/openclaw_restart_gateway.sh",
    "_internal/bundled_runtime/oauth/openai-codex.js",
    MACOS_REQUIRED_SYMLINK_SUFFIX,
)
REQUIRED_PYINSTALLER_MODULES = ("openclaw_oauth_switcher", "requests", "rich")


class CliArgs(argparse.Namespace):
    asset: str = ""
    platform: str = ""
    runtime_root: str | None = None


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Verify release archives contain critical OpenAI Hub runtime files."
    )
    _ = parser.add_argument(
        "--asset", required=True, help="Path to the release archive"
    )
    _ = parser.add_argument(
        "--platform",
        required=True,
        choices=("windows", "macos"),
        help="Archive platform type",
    )
    _ = parser.add_argument(
        "--runtime-root",
        help="Optional unpacked PyInstaller runtime directory to smoke-test before upload",
    )
    return parser.parse_args(namespace=CliArgs())


def ensure_required_entries(
    entries: Iterable[str], required_paths: tuple[str, ...], archive_label: str
) -> None:
    entry_list = list(entries)
    entry_set = set(entry_list)
    missing = [
        relative_path
        for relative_path in required_paths
        if not any(
            entry == relative_path or entry.endswith(f"/{relative_path}")
            for entry in entry_set
        )
    ]
    if missing:
        raise RuntimeError(
            f"{archive_label} is missing required entries: {', '.join(missing)}"
        )


def verify_windows_asset(asset_path: Path) -> None:
    with zipfile.ZipFile(asset_path) as archive:
        ensure_required_entries(
            archive.namelist(), WINDOWS_REQUIRED_SUFFIXES, "Archive"
        )


def verify_macos_asset(asset_path: Path) -> None:
    with tarfile.open(asset_path, "r:gz") as archive:
        members = archive.getmembers()
        ensure_required_entries(
            (member.name for member in members), MACOS_REQUIRED_SUFFIXES, "Archive"
        )
        python_entry = next(
            (
                member
                for member in members
                if member.name.endswith(MACOS_REQUIRED_SYMLINK_SUFFIX)
            ),
            None,
        )
        if python_entry is None:
            raise RuntimeError(
                f"Archive is missing required symlink entry: {MACOS_REQUIRED_SYMLINK_SUFFIX}"
            )
        if not python_entry.issym():
            raise RuntimeError(
                f"Archive entry {python_entry.name} must stay a symlink to preserve the PyInstaller layout"
            )
        if python_entry.linkname != MACOS_REQUIRED_SYMLINK_TARGET:
            raise RuntimeError(
                f"Archive entry {python_entry.name} must point to {MACOS_REQUIRED_SYMLINK_TARGET}, got {python_entry.linkname}"
            )


def ensure_runtime_paths(runtime_root: Path, required_paths: tuple[str, ...]) -> None:
    missing = [
        relative_path
        for relative_path in required_paths
        if not (runtime_root / relative_path).exists()
    ]
    if missing:
        raise RuntimeError(
            f"Runtime directory is missing required paths: {', '.join(missing)}"
        )


def read_embedded_module_names(executable_path: Path) -> set[str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller.utils.cliutils.archive_viewer",
            str(executable_path),
            "-r",
            "-b",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"archive_viewer failed for {executable_path.name}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def smoke_test_runtime_executable(executable_path: Path) -> None:
    completed = subprocess.run(
        [str(executable_path), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Runtime executable failed smoke test: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    if "OpenAI Hub" not in completed.stdout:
        raise RuntimeError(
            f"Runtime executable returned unexpected version output: {completed.stdout.strip()}"
        )


def verify_runtime_root(runtime_root: Path, platform: str) -> None:
    if not runtime_root.is_dir():
        raise RuntimeError(f"Runtime directory not found: {runtime_root}")

    if platform == "windows":
        ensure_runtime_paths(runtime_root, WINDOWS_RUNTIME_REQUIRED_PATHS)
        executable_path = runtime_root / "openaihub.exe"
    else:
        ensure_runtime_paths(runtime_root, MACOS_RUNTIME_REQUIRED_PATHS)
        python_symlink = runtime_root / MACOS_REQUIRED_SYMLINK_SUFFIX
        if not python_symlink.is_symlink():
            raise RuntimeError(
                f"Runtime directory entry {python_symlink} must stay a symlink to preserve the PyInstaller layout"
            )
        if (
            Path(str(python_symlink.readlink())).as_posix()
            != MACOS_REQUIRED_SYMLINK_TARGET
        ):
            raise RuntimeError(
                f"Runtime directory entry {python_symlink} must point to {MACOS_REQUIRED_SYMLINK_TARGET}"
            )
        executable_path = runtime_root / "openaihub-bin"

    smoke_test_runtime_executable(executable_path)
    embedded_modules = read_embedded_module_names(executable_path)
    missing_modules = [
        module_name
        for module_name in REQUIRED_PYINSTALLER_MODULES
        if module_name not in embedded_modules
    ]
    if missing_modules:
        raise RuntimeError(
            f"Runtime executable is missing embedded modules: {', '.join(missing_modules)}"
        )


def main() -> int:
    args = parse_args()
    asset_path = Path(args.asset).resolve()
    if not asset_path.is_file():
        raise RuntimeError(f"Asset not found: {asset_path}")

    if args.platform == "windows":
        verify_windows_asset(asset_path)
    else:
        verify_macos_asset(asset_path)

    if args.runtime_root:
        verify_runtime_root(Path(args.runtime_root).resolve(), args.platform)

    print(f"Verified release asset: {asset_path.name}")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        raise SystemExit(exit_code)
    except Exception as error:  # noqa: BLE001
        print(f"Release asset verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
