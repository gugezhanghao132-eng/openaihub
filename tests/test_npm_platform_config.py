import json
import subprocess
import unittest
from pathlib import Path


NPM_DIR = Path(__file__).resolve().parents[1] / "npm"
ROOT_DIR = Path(__file__).resolve().parents[1]


def resolve_platform_config(platform: str, arch: str) -> dict[str, object]:
    script = (
        "const { resolvePlatformConfig } = require('./lib/config');"
        f"const result = resolvePlatformConfig('{platform}', '{arch}');"
        "process.stdout.write(JSON.stringify(result));"
    )
    output = subprocess.check_output(
        ["node", "-e", script],
        cwd=NPM_DIR,
        text=True,
    )
    return json.loads(output)


def resolve_runtime_root() -> str:
    script = (
        "const { runtimeRoot } = require('./lib/config');"
        "process.stdout.write(String(runtimeRoot));"
    )
    return subprocess.check_output(
        ["node", "-e", script],
        cwd=NPM_DIR,
        text=True,
    ).strip()


class NpmPlatformConfigTests(unittest.TestCase):
    def test_runtime_root_stays_under_openaihub_npm_runtime(self) -> None:
        runtime_root = resolve_runtime_root().replace("\\", "/")

        self.assertTrue(runtime_root.endswith("/.openaihub/npm-runtime"))

    def test_resolve_platform_config_supports_macos_arm64(self) -> None:
        result = resolve_platform_config("darwin", "arm64")

        self.assertEqual(result["assetName"], "openaihub-macos-arm64.tar.gz")
        self.assertEqual(result["extractKind"], "tar.gz")
        self.assertEqual(result["runtimeKey"], "darwin-arm64")
        self.assertEqual(result["executableRelativePath"], "openaihub-bin")

    def test_resolve_platform_config_supports_macos_x64(self) -> None:
        result = resolve_platform_config("darwin", "x64")

        self.assertEqual(result["assetName"], "openaihub-macos-x64.tar.gz")
        self.assertEqual(result["extractKind"], "tar.gz")
        self.assertEqual(result["runtimeKey"], "darwin-x64")
        self.assertEqual(result["executableRelativePath"], "openaihub-bin")

    def test_resolve_platform_config_rejects_unsupported_linux(self) -> None:
        script = (
            "const { resolvePlatformConfig } = require('./lib/config');"
            "try { resolvePlatformConfig('linux', 'x64'); }"
            "catch (error) { process.stdout.write(String(error.message || error)); process.exit(0); }"
            "process.exit(1);"
        )
        output = subprocess.check_output(
            ["node", "-e", script],
            cwd=NPM_DIR,
            text=True,
        )

        self.assertIn("linux-x64", output)

    def test_windows_uninstall_script_preserves_user_openaihub_directory(self) -> None:
        script = (ROOT_DIR / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")

        self.assertNotIn("Remove-Item -Path $using:InstallRoot -Recurse -Force", script)

    def test_unix_uninstall_script_preserves_user_openaihub_directory(self) -> None:
        script = (ROOT_DIR / "scripts" / "uninstall.sh").read_text(encoding="utf-8")

        self.assertNotIn('rm -rf "$INSTALL_ROOT"', script)
