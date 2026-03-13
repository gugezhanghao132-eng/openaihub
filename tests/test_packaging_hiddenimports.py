import unittest
from pathlib import Path


SPEC_PATH = Path(__file__).resolve().parents[1] / "openaihub.spec"


class PackagingHiddenImportsTests(unittest.TestCase):
    def test_spec_includes_switcher_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openclaw_oauth_switcher", spec_text)

    def test_spec_includes_local_api_gateway_hiddenimport(self) -> None:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
        self.assertIn("openai_hub_api_gateway", spec_text)


if __name__ == "__main__":
    unittest.main()
