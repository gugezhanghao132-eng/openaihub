import unittest
from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "openaihub.spec"
ROOT = Path(__file__).resolve().parents[1]


class PackagingHiddenImportsTests(unittest.TestCase):
    def test_spec_includes_switcher_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw_oauth_switcher", spec_text)

    def test_spec_includes_local_api_gateway_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openai_hub_api_gateway", spec_text)

    def test_spec_includes_gateway_restart_scripts_as_datas(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw_restart_gateway.ps1", spec_text)
        self.assertIn("openclaw_restart_gateway.sh", spec_text)

    def test_macos_build_script_copies_gateway_restart_scripts(self) -> None:
        script_path = ROOT / "scripts" / "build-macos.sh"
        script_text = script_path.read_text(encoding="utf-8")
        self.assertIn("openclaw_restart_gateway.ps1", script_text)
        self.assertIn("openclaw_restart_gateway.sh", script_text)

    def test_release_workflow_copies_windows_restart_scripts(self) -> None:
        workflow_path = ROOT / ".github" / "workflows" / "build-release-assets.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        self.assertIn("openclaw_restart_gateway.ps1", workflow_text)
        self.assertIn("openclaw_restart_gateway.sh", workflow_text)


if __name__ == "__main__":
    unittest.main()
