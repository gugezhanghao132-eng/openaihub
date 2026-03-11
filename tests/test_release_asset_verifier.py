import importlib.util
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = ROOT_DIR / "scripts" / "verify_release_asset.py"


class VerifyScriptModule(Protocol):
    subprocess: ModuleType

    def verify_runtime_root(self, runtime_root: Path, platform: str) -> None: ...


VERIFY_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "verify_release_asset", VERIFY_SCRIPT
)
assert VERIFY_SCRIPT_SPEC is not None
assert VERIFY_SCRIPT_SPEC.loader is not None
verify_script_module = importlib.util.module_from_spec(VERIFY_SCRIPT_SPEC)
VERIFY_SCRIPT_SPEC.loader.exec_module(verify_script_module)
VERIFY_SCRIPT_MODULE = cast(VerifyScriptModule, cast(object, verify_script_module))


class ReleaseAssetVerifierTests(unittest.TestCase):
    def test_windows_archive_with_required_entries_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "openaihub-windows.zip"
            with zipfile.ZipFile(asset_path, "w") as archive:
                archive.writestr("openaihub.exe", "")
                archive.writestr("openai_codex_login_helper.mjs", "")
                archive.writestr("openclaw_restart_gateway.ps1", "")
                archive.writestr("openclaw_restart_gateway.sh", "")
                archive.writestr("bundled_runtime/oauth/openai-codex.js", "")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--asset",
                    str(asset_path),
                    "--platform",
                    "windows",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Verified release asset", completed.stdout)

    def test_windows_archive_missing_oauth_runtime_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "openaihub-windows.zip"
            with zipfile.ZipFile(asset_path, "w") as archive:
                archive.writestr("openaihub.exe", "")
                archive.writestr("openai_codex_login_helper.mjs", "")
                archive.writestr("openclaw_restart_gateway.ps1", "")
                archive.writestr("openclaw_restart_gateway.sh", "")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--asset",
                    str(asset_path),
                    "--platform",
                    "windows",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("bundled_runtime/oauth/openai-codex.js", completed.stderr)

    def test_runtime_root_requires_embedded_requests_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "openaihub"
            internal_dir = runtime_root / "_internal"
            oauth_dir = internal_dir / "bundled_runtime" / "oauth"
            oauth_dir.mkdir(parents=True)
            _ = (runtime_root / "openaihub.exe").write_text("", encoding="utf-8")
            _ = (internal_dir / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")

            with mock.patch.object(
                VERIFY_SCRIPT_MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        args=["openaihub.exe", "--version"],
                        returncode=0,
                        stdout="OpenAI Hub 1.1.15\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["archive_viewer"],
                        returncode=0,
                        stdout="openclaw_oauth_switcher\nrich\n",
                        stderr="",
                    ),
                ],
            ):
                with self.assertRaisesRegex(RuntimeError, "requests"):
                    VERIFY_SCRIPT_MODULE.verify_runtime_root(runtime_root, "windows")

    def test_runtime_root_passes_with_required_embedded_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "openaihub"
            internal_dir = runtime_root / "_internal"
            oauth_dir = internal_dir / "bundled_runtime" / "oauth"
            oauth_dir.mkdir(parents=True)
            _ = (runtime_root / "openaihub.exe").write_text("", encoding="utf-8")
            _ = (internal_dir / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")

            with mock.patch.object(
                VERIFY_SCRIPT_MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        args=["openaihub.exe", "--version"],
                        returncode=0,
                        stdout="OpenAI Hub 1.1.15\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["archive_viewer"],
                        returncode=0,
                        stdout="openclaw_oauth_switcher\nrequests\nrich\n",
                        stderr="",
                    ),
                ],
            ):
                VERIFY_SCRIPT_MODULE.verify_runtime_root(runtime_root, "windows")

    def test_macos_runtime_root_requires_expected_python_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "openaihub-macos-arm64"
            internal_dir = runtime_root / "_internal"
            oauth_dir = internal_dir / "bundled_runtime" / "oauth"
            oauth_dir.mkdir(parents=True)
            _ = (runtime_root / "openaihub").write_text("", encoding="utf-8")
            _ = (runtime_root / "OAH").write_text("", encoding="utf-8")
            _ = (runtime_root / "openaihub-bin").write_text("", encoding="utf-8")
            _ = (internal_dir / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")
            _ = (internal_dir / "Python.framework" / "Versions" / "3.12").mkdir(
                parents=True
            )
            python_path = internal_dir / "Python"
            _ = python_path.write_text("", encoding="utf-8")

            original_is_symlink = Path.is_symlink

            def fake_is_symlink(path: Path) -> bool:
                if path == python_path:
                    return True
                return original_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", fake_is_symlink):
                with mock.patch.object(
                    Path, "readlink", return_value=Path("Python.framework/Wrong/Python")
                ):
                    with self.assertRaisesRegex(RuntimeError, "must point to"):
                        VERIFY_SCRIPT_MODULE.verify_runtime_root(runtime_root, "macos")

    def test_macos_runtime_root_passes_with_expected_python_symlink_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "openaihub-macos-arm64"
            internal_dir = runtime_root / "_internal"
            oauth_dir = internal_dir / "bundled_runtime" / "oauth"
            oauth_dir.mkdir(parents=True)
            _ = (runtime_root / "openaihub").write_text("", encoding="utf-8")
            _ = (runtime_root / "OAH").write_text("", encoding="utf-8")
            _ = (runtime_root / "openaihub-bin").write_text("", encoding="utf-8")
            _ = (internal_dir / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (internal_dir / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")
            _ = (internal_dir / "Python.framework" / "Versions" / "3.12").mkdir(
                parents=True
            )
            python_path = internal_dir / "Python"
            _ = python_path.write_text("", encoding="utf-8")

            original_is_symlink = Path.is_symlink

            def fake_is_symlink(path: Path) -> bool:
                if path == python_path:
                    return True
                return original_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", fake_is_symlink):
                with mock.patch.object(
                    Path,
                    "readlink",
                    return_value=Path("Python.framework/Versions/3.12/Python"),
                ):
                    with mock.patch.object(
                        VERIFY_SCRIPT_MODULE.subprocess,
                        "run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                args=["openaihub-bin", "--version"],
                                returncode=0,
                                stdout="OpenAI Hub 1.1.15\n",
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                args=["archive_viewer"],
                                returncode=0,
                                stdout="openclaw_oauth_switcher\nrequests\nrich\n",
                                stderr="",
                            ),
                        ],
                    ):
                        VERIFY_SCRIPT_MODULE.verify_runtime_root(runtime_root, "macos")

    def test_macos_archive_with_symlink_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "openaihub-macos-arm64"
            internal_dir = source_root / "_internal"
            oauth_dir = source_root / "bundled_runtime" / "oauth"
            internal_dir.mkdir(parents=True)
            oauth_dir.mkdir(parents=True)
            _ = (source_root / "openaihub").write_text("", encoding="utf-8")
            _ = (source_root / "OAH").write_text("", encoding="utf-8")
            _ = (source_root / "openaihub-bin").write_text("", encoding="utf-8")
            _ = (source_root / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")
            (internal_dir / "Python.framework").mkdir()

            asset_path = Path(temp_dir) / "openaihub-macos-arm64.tar.gz"
            with tarfile.open(asset_path, "w:gz") as archive:
                archive.add(source_root, arcname=source_root.name, recursive=True)
                python_link = tarfile.TarInfo(
                    name=f"{source_root.name}/_internal/Python"
                )
                python_link.type = tarfile.SYMTYPE
                python_link.linkname = "Python.framework/Versions/3.12/Python"
                archive.addfile(python_link)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--asset",
                    str(asset_path),
                    "--platform",
                    "macos",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Verified release asset", completed.stdout)

    def test_macos_archive_with_wrong_python_symlink_target_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "openaihub-macos-arm64"
            internal_dir = source_root / "_internal"
            oauth_dir = source_root / "bundled_runtime" / "oauth"
            internal_dir.mkdir(parents=True)
            oauth_dir.mkdir(parents=True)
            _ = (source_root / "openaihub").write_text("", encoding="utf-8")
            _ = (source_root / "OAH").write_text("", encoding="utf-8")
            _ = (source_root / "openaihub-bin").write_text("", encoding="utf-8")
            _ = (source_root / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")

            asset_path = Path(temp_dir) / "openaihub-macos-arm64.tar.gz"
            with tarfile.open(asset_path, "w:gz") as archive:
                archive.add(source_root, arcname=source_root.name, recursive=True)
                python_link = tarfile.TarInfo(
                    name=f"{source_root.name}/_internal/Python"
                )
                python_link.type = tarfile.SYMTYPE
                python_link.linkname = "Python.framework/Wrong/Python"
                archive.addfile(python_link)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--asset",
                    str(asset_path),
                    "--platform",
                    "macos",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must point to", completed.stderr)

    def test_macos_archive_without_python_symlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "openaihub-macos-arm64"
            internal_dir = source_root / "_internal"
            oauth_dir = source_root / "bundled_runtime" / "oauth"
            internal_dir.mkdir(parents=True)
            oauth_dir.mkdir(parents=True)
            _ = (source_root / "openaihub").write_text("", encoding="utf-8")
            _ = (source_root / "OAH").write_text("", encoding="utf-8")
            _ = (source_root / "openaihub-bin").write_text("", encoding="utf-8")
            _ = (source_root / "openai_codex_login_helper.mjs").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.ps1").write_text(
                "", encoding="utf-8"
            )
            _ = (source_root / "openclaw_restart_gateway.sh").write_text(
                "", encoding="utf-8"
            )
            _ = (oauth_dir / "openai-codex.js").write_text("", encoding="utf-8")
            _ = (internal_dir / "Python").write_text("", encoding="utf-8")

            asset_path = Path(temp_dir) / "openaihub-macos-arm64.tar.gz"
            with tarfile.open(asset_path, "w:gz") as archive:
                archive.add(source_root, arcname=source_root.name, recursive=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_SCRIPT),
                    "--asset",
                    str(asset_path),
                    "--platform",
                    "macos",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("must stay a symlink", completed.stderr)


if __name__ == "__main__":
    _ = unittest.main()
