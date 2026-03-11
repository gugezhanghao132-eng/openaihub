import unittest
from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "openaihub.spec"
ROOT_DIR = Path(__file__).resolve().parents[1]


class PackagingHiddenImportsTests(unittest.TestCase):
    def test_spec_includes_switcher_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw_oauth_switcher", spec_text)

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


if __name__ == "__main__":
    unittest.main()
