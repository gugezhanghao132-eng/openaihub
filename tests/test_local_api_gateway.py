import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "package" / "app"
GATEWAY_PATH = APP_DIR / "openai_hub_api_gateway.py"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class LocalAPIGatewayTests(unittest.TestCase):
    def test_ensure_gateway_config_creates_and_persists_api_key(self) -> None:
        gateway = load_module("openai_hub_api_gateway_config", GATEWAY_PATH)
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            created = gateway.ensure_gateway_config(root)
            loaded = gateway.ensure_gateway_config(root)

        self.assertEqual(created["host"], gateway.DEFAULT_API_HOST)
        self.assertEqual(created["port"], gateway.DEFAULT_API_PORT)
        self.assertTrue(str(created["apiKey"]).strip())
        self.assertEqual(loaded["apiKey"], created["apiKey"])

    def test_build_codex_request_translates_chat_messages(self) -> None:
        gateway = load_module("openai_hub_api_gateway_request", GATEWAY_PATH)
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        }

        translated = gateway.build_codex_chat_request(payload)

        self.assertEqual(translated["model"], "gpt-5.4")
        self.assertFalse(translated["store"])
        self.assertEqual(translated["instructions"], "You are helpful.")
        self.assertEqual(translated["input"][0]["role"], "user")
        self.assertEqual(translated["input"][0]["content"][0]["text"], "Hello")
        self.assertEqual(translated["input"][1]["role"], "assistant")

    def test_collect_stream_response_uses_completed_assistant_output(self) -> None:
        gateway = load_module("openai_hub_api_gateway_stream_collect", GATEWAY_PATH)
        lines = [
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":"OK"}',
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"OK"}]}],"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}}',
        ]

        payload = gateway.collect_stream_response(lines)

        self.assertEqual(payload["output"][0]["content"][0]["text"], "OK")
        self.assertEqual(payload["usage"]["total_tokens"], 15)

    def test_check_api_key_accepts_matching_bearer_token(self) -> None:
        gateway = load_module("openai_hub_api_gateway_auth", GATEWAY_PATH)
        headers = {"Authorization": "Bearer secret-key"}

        self.assertTrue(gateway.is_request_authorized(headers, "secret-key"))
        self.assertFalse(gateway.is_request_authorized(headers, "wrong-key"))
        self.assertFalse(gateway.is_request_authorized({}, "secret-key"))

    def test_build_codex_request_rejects_streaming_for_now(self) -> None:
        gateway = load_module("openai_hub_api_gateway_stream", GATEWAY_PATH)

        with self.assertRaises(ValueError):
            gateway.build_codex_chat_request(
                {
                    "model": "gpt-5.4",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            )

    def test_service_lists_models_using_defaults(self) -> None:
        gateway = load_module("openai_hub_api_gateway_models", GATEWAY_PATH)
        service = gateway.LocalAPIGatewayService(root=Path("."))

        payload = service.build_models_payload()
        model_ids = [item["id"] for item in payload["data"]]

        self.assertIn(service.default_model, model_ids)

    def test_service_retries_with_refreshed_profile(self) -> None:
        gateway = load_module("openai_hub_api_gateway_retry", GATEWAY_PATH)

        class FakeSwitcher:
            ROOT = Path(".")

            @staticmethod
            def load_store(_root: Path):
                return {
                    "active": "alpha",
                    "accounts": {
                        "alpha": {
                            "type": "oauth",
                            "provider": "openai-codex",
                            "access": "old-access",
                            "refresh": "refresh-alpha",
                            "expires": 1,
                            "accountId": "acct-alpha",
                        }
                    },
                }

            @staticmethod
            def save_store(data, _root: Path):
                FakeSwitcher.saved = data

            @staticmethod
            def normalize_saved_profile(profile):
                return dict(profile)

            @staticmethod
            def get_selected_alias(_root: Path):
                return "alpha"

            @staticmethod
            def build_dashboard_rows(root, **_kwargs):
                return [
                    {
                        "alias": "alpha",
                        "displayName": "alpha",
                        "accountId": "acct-alpha",
                        "isCurrent": True,
                        "plan": "plus",
                        "windows": [],
                        "groups": [],
                        "error": None,
                        "warning": None,
                    }
                ]

            class DashboardState:
                def __init__(self, rows=None):
                    self.rows = list(rows or [])

            @staticmethod
            def apply_auto_switch_if_needed(state, **_kwargs):
                return None

            @staticmethod
            def refresh_openai_codex_token(profile, **_kwargs):
                profile["access"] = "new-access"
                profile["refresh"] = "refresh-alpha-2"
                return profile

        attempts = {"count": 0}

        class FakeResponse:
            def __init__(self, status_code: int, payload: dict[str, object]):
                self.status_code = status_code
                self._payload = payload
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

            def iter_lines(self, decode_unicode=False):
                _ = decode_unicode
                yield from ()

        class FakeStreamResponse:
            def __init__(self, status_code: int, lines: list[bytes]):
                self.status_code = status_code
                self._lines = lines
                self.text = b"\n".join(lines).decode("utf-8", errors="replace")

            def json(self):
                raise AssertionError("streaming response should not use json()")

            def iter_lines(self, decode_unicode=False):
                if decode_unicode:
                    for line in self._lines:
                        yield line.decode("utf-8")
                    return
                yield from self._lines

        def fake_post(_url, headers=None, json=None, timeout=None, stream=None):
            _ = (headers, json, timeout, stream)
            attempts["count"] += 1
            if attempts["count"] == 1:
                return FakeResponse(401, {"error": {"message": "expired"}})
            return FakeStreamResponse(
                200,
                [
                    b"event: response.output_text.delta",
                    b'data: {"type":"response.output_text.delta","delta":"done"}',
                    b"event: response.completed",
                    b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
                ],
            )

        service = gateway.LocalAPIGatewayService(
            root=Path("."),
            switcher_module=FakeSwitcher,
            requests_post=fake_post,
        )

        result = service.handle_chat_completions(
            {
                "model": "gpt-5.4",
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result["choices"][0]["message"]["content"], "done")
        self.assertEqual(
            FakeSwitcher.saved["accounts"]["alpha"]["access"],
            "new-access",
        )

    def test_extract_output_text_ignores_compaction_echo(self) -> None:
        gateway = load_module("openai_hub_api_gateway_compaction", GATEWAY_PATH)
        payload = {
            "object": "response.compaction",
            "output": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Reply with OK only"}],
                },
                {"type": "compaction_summary", "encrypted_content": "..."},
            ],
        }

        self.assertEqual(gateway._extract_output_text(payload), "")


if __name__ == "__main__":
    unittest.main()
