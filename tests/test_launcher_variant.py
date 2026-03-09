import importlib.util
import os
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "package" / "app"
LAUNCHER_PATH = APP_DIR / "openai_launcher.py"
SWITCHER_PATH = APP_DIR / "openclaw_oauth_switcher.py"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LauncherVariantTests(unittest.TestCase):
    def test_launcher_applies_selected_variant_before_switcher_main(self) -> None:
        original_argv = list(sys.argv)
        original_env = os.environ.get("GT_VARIANT")
        for name in ["openclaw_oauth_switcher", "openai_launcher"]:
            sys.modules.pop(name, None)

        try:
            os.environ.pop("GT_VARIANT", None)
            switcher = load_module("openclaw_oauth_switcher", SWITCHER_PATH)
            launcher = load_module("openai_launcher", LAUNCHER_PATH)
            seen_variants: list[str] = []

            setattr(switcher, "choose_from_menu", lambda **_kwargs: {"key": "opencode"})
            setattr(switcher, "hide_cursor", lambda: None)
            setattr(
                switcher,
                "main",
                lambda: seen_variants.append(switcher.get_app_variant()) or 0,
            )

            sys.argv = [str(LAUNCHER_PATH)]
            exit_code = launcher.main()
        finally:
            sys.argv = original_argv
            if original_env is None:
                os.environ.pop("GT_VARIANT", None)
            else:
                os.environ["GT_VARIANT"] = original_env
            for name in ["openclaw_oauth_switcher", "openai_launcher"]:
                sys.modules.pop(name, None)

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_variants, ["opencode"])


if __name__ == "__main__":
    unittest.main()
