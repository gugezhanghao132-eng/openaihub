import unittest
from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "openaihub.spec"
ROOT_DIR = Path(__file__).resolve().parents[1]


class PackagingHiddenImportsTests(unittest.TestCase):
    def test_spec_resolves_repo_root_from_spec_path(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")

        self.assertIn("ROOT = Path(SPEC).resolve().parent", spec_text)

    def test_spec_includes_switcher_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw_oauth_switcher", spec_text)

    def test_spec_includes_runtime_http_and_ui_dependencies(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")

        self.assertIn("'requests'", spec_text)
        self.assertIn("'rich'", spec_text)

    def test_spec_bundles_openclaw_restart_helpers(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")

        self.assertIn("openclaw_restart_gateway.ps1", spec_text)
        self.assertIn("openclaw_restart_gateway.sh", spec_text)

    def test_release_workflows_accept_v_and_openaihub_v_tags(self) -> None:
        workflow_paths = [
            ROOT_DIR / ".github" / "workflows" / "build-release-assets.yml",
            ROOT_DIR / ".github" / "workflows" / "publish-npm.yml",
        ]

        for workflow_path in workflow_paths:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            self.assertIn("- 'v*'", workflow_text)
            self.assertIn("- 'openaihub-v*'", workflow_text)

    def test_release_workflow_installs_packaging_requirements_file(self) -> None:
        workflow_text = (
            ROOT_DIR / ".github" / "workflows" / "build-release-assets.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("scripts/build-requirements.txt", workflow_text)
        self.assertIn("Install Python build requirements", workflow_text)

    def test_release_workflow_verifies_built_archives_before_upload(self) -> None:
        workflow_text = (
            ROOT_DIR / ".github" / "workflows" / "build-release-assets.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "verify_release_asset.py --asset release-assets/openaihub-windows.zip --platform windows --runtime-root dist/openaihub",
            workflow_text,
        )
        self.assertIn(
            'verify_release_asset.py --asset "release-assets/${{ matrix.expected_asset }}" --platform macos --runtime-root "dist/${{ matrix.runtime_dir }}"',
            workflow_text,
        )
        self.assertIn("runtime_dir: openaihub-macos-x64", workflow_text)
        self.assertIn("runtime_dir: openaihub-macos-arm64", workflow_text)

    def test_macos_build_script_uses_shared_spec_file(self) -> None:
        script_text = (ROOT_DIR / "scripts" / "build-macos.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('SPEC_FILE="$ROOT_DIR/openaihub.spec"', script_text)
        self.assertIn('python3 -m PyInstaller "$SPEC_FILE" -y', script_text)

    def test_build_requirements_include_runtime_ui_dependencies(self) -> None:
        requirements_text = (ROOT_DIR / "scripts" / "build-requirements.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn("pyinstaller", requirements_text)
        self.assertIn("requests", requirements_text)
        self.assertIn("rich", requirements_text)


if __name__ == "__main__":
    _ = unittest.main()
