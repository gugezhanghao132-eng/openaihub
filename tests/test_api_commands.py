import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SWITCHER_PATH = (
    Path(__file__).resolve().parents[1]
    / "package"
    / "app"
    / "openclaw_oauth_switcher.py"
)


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class APICommandTests(unittest.TestCase):
    def test_main_menu_includes_api_config_option(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_menu", None)
        switcher = load_module("openclaw_oauth_switcher_api_menu", SWITCHER_PATH)

        options = switcher.build_main_menu_options()
        keys = [str(item.get("key") or "") for item in options]

        self.assertIn("api-config", keys)

    def test_parser_includes_api_commands(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_parser", None)
        switcher = load_module("openclaw_oauth_switcher_api_parser", SWITCHER_PATH)

        parser = switcher.parser()
        help_text = parser.format_help()

        self.assertIn("api-config", help_text)
        self.assertIn("api-info", help_text)
        self.assertIn("api-serve", help_text)

    def test_api_info_command_prints_gateway_details(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_info", None)
        switcher = load_module("openclaw_oauth_switcher_api_info", SWITCHER_PATH)

        class FakeGatewayModule:
            @staticmethod
            def ensure_gateway_config(_root):
                return {
                    "host": "127.0.0.1",
                    "port": 8321,
                    "apiKey": "demo-key",
                    "stateFile": "demo-state.json",
                }

        setattr(switcher, "load_api_gateway_module", lambda: FakeGatewayModule)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = switcher.cmd_api_info()

        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("http://127.0.0.1:8321", output)
        self.assertIn("demo-key", output)

    def test_api_config_command_prints_gateway_details(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_config", None)
        switcher = load_module("openclaw_oauth_switcher_api_config", SWITCHER_PATH)

        class FakeGatewayModule:
            @staticmethod
            def ensure_gateway_config(_root):
                return {
                    "host": "127.0.0.1",
                    "port": 9321,
                    "apiKey": "config-key",
                    "stateFile": "config-state.json",
                }

        setattr(switcher, "load_api_gateway_module", lambda: FakeGatewayModule)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = switcher.cmd_api_config()

        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("http://127.0.0.1:9321", output)
        self.assertIn("config-key", output)

    def test_update_api_key_persists_custom_value(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_key_update", None)
        switcher = load_module("openclaw_oauth_switcher_api_key_update", SWITCHER_PATH)

        recorded: dict[str, object] = {}

        class FakeGatewayModule:
            @staticmethod
            def set_gateway_api_key(_root, api_key):
                recorded["apiKey"] = api_key
                return {
                    "host": "127.0.0.1",
                    "port": 8321,
                    "apiKey": api_key,
                    "stateFile": "state.json",
                }

        setattr(switcher, "load_api_gateway_module", lambda: FakeGatewayModule)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = switcher.cmd_api_set_key("manual-key")

        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(recorded["apiKey"], "manual-key")
        self.assertIn("manual-key", output)


if __name__ == "__main__":
    unittest.main()
