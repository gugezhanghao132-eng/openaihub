import importlib.util
import http.client
import json
import threading
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
    def test_running_gateway_applies_updated_api_key_without_restart(self) -> None:
        gateway = load_module("openai_hub_api_gateway_live_key", GATEWAY_PATH)

        class FakeSwitcher:
            ROOT = Path(".")

            @staticmethod
            def read_json(path: Path):
                if not path.exists():
                    return {}
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)

            @staticmethod
            def write_json(path: Path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle)

            @staticmethod
            def load_store(_root: Path):
                return {"version": 1, "active": None, "accounts": {}}

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_switcher = getattr(gateway, "SWITCHER")
            setattr(gateway, "SWITCHER", FakeSwitcher)
            try:
                config = gateway.ensure_gateway_config(root)
                service = gateway.LocalAPIGatewayService(
                    root=root, switcher_module=FakeSwitcher
                )
                old_key = str(config["apiKey"])
                gateway.set_gateway_api_key(root, "123456")
                current_key = service.current_api_key()

                self.assertFalse(
                    gateway.is_request_authorized(
                        {"Authorization": f"Bearer {old_key}"}, current_key
                    )
                )
                self.assertTrue(
                    gateway.is_request_authorized(
                        {"Authorization": "Bearer 123456"}, current_key
                    )
                )
                payload = service.build_models_payload()
                self.assertEqual(payload["object"], "list")
            finally:
                setattr(gateway, "SWITCHER", original_switcher)

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
        self.assertEqual(translated["input"][0]["content"][0]["type"], "input_text")
        self.assertEqual(translated["input"][0]["content"][0]["text"], "Hello")
        self.assertEqual(translated["input"][1]["role"], "assistant")
        self.assertEqual(translated["input"][1]["content"][0]["type"], "output_text")
        self.assertEqual(translated["input"][1]["content"][0]["text"], "Hi")

    def test_build_codex_request_translates_anthropic_messages(self) -> None:
        gateway = load_module("openai_hub_api_gateway_anthropic_request", GATEWAY_PATH)
        payload = {
            "model": "gpt-5.4",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 128,
            "reasoning_effort": "high",
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["model"], "gpt-5.4")
        self.assertEqual(translated["instructions"], "You are helpful.")
        self.assertEqual(translated["input"][0]["role"], "user")
        self.assertEqual(translated["input"][0]["content"][0]["type"], "input_text")
        self.assertEqual(translated["input"][0]["content"][0]["text"], "Hello")
        self.assertEqual(translated["reasoning"]["effort"], "high")
        self.assertNotIn("max_output_tokens", translated)

    def test_build_codex_request_translates_anthropic_tool_loop(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_tools", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "read_file",
                            "input": {"path": "README.md"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "file text",
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["tools"][0]["name"], "read_file")
        self.assertEqual(translated["input"][0]["type"], "function_call")
        self.assertEqual(translated["input"][1]["type"], "function_call_output")
        self.assertEqual(translated["input"][1]["call_id"], "toolu_1")
        self.assertNotIn("is_error", translated["input"][1])

    def test_build_codex_request_translates_anthropic_image_block(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_image", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgo=",
                            },
                        },
                    ],
                }
            ],
        }

        translated = gateway.build_codex_anthropic_request(payload)

        message = translated["input"][0]
        self.assertEqual(message["type"], "message")
        self.assertEqual(message["role"], "user")
        self.assertEqual(
            message["content"],
            [
                {"type": "input_text", "text": "What is in this image?"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,iVBORw0KGgo=",
                },
            ],
        )

    def test_build_codex_request_keeps_explicit_xhigh_reasoning_effort(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_reasoning_effort", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "reasoning_effort": "xhigh",
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["reasoning"]["effort"], "xhigh")

    def test_build_codex_request_maps_claude_output_config_effort(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_claude_output_config_effort", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["reasoning"]["effort"], "high")

    def test_build_codex_request_maps_claude_max_effort_to_xhigh(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_claude_output_config_max_effort", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "max"},
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["reasoning"]["effort"], "xhigh")

    def test_build_codex_request_defaults_claude_adaptive_thinking_to_high_effort(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_claude_adaptive_default_effort", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertEqual(translated["reasoning"]["effort"], "high")

    def test_build_codex_request_enables_parallel_tool_calls_for_claude_code_tools(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_parallel_tool_calls", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertTrue(translated["parallel_tool_calls"])

    def test_build_codex_request_adds_claude_code_agentic_compatibility_preamble(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_agentic_compatibility_preamble", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
            "context_management": {"clear_function_results": False},
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ],
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertIn("Claude Code compatibility mode", translated["instructions"])
        self.assertTrue(translated["instructions"].endswith("You are helpful."))

    def test_build_codex_request_adds_claude_code_task_budget_note(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_task_budget_note", GATEWAY_PATH
        )
        payload = {
            "model": "gpt-5.4",
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "task_budget": {"type": "tokens", "total": 120000, "remaining": 80000}
            },
        }

        translated = gateway.build_codex_anthropic_request(payload)

        self.assertIn("Task budget", translated["instructions"])
        self.assertIn("120000", translated["instructions"])
        self.assertIn("80000", translated["instructions"])

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

    def test_collect_stream_response_rebuilds_text_when_completed_output_is_empty(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_stream_collect_empty_output", GATEWAY_PATH
        )
        lines = [
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":"Hello"}',
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":" world"}',
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[],"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}}',
        ]

        payload = gateway.collect_stream_response(lines)

        self.assertEqual(payload["output"][0]["content"][0]["text"], "Hello world")
        self.assertEqual(payload["usage"]["total_tokens"], 15)

    def test_check_api_key_accepts_matching_bearer_token(self) -> None:
        gateway = load_module("openai_hub_api_gateway_auth", GATEWAY_PATH)
        headers = {"Authorization": "Bearer secret-key"}

        self.assertTrue(gateway.is_request_authorized(headers, "secret-key"))
        self.assertFalse(gateway.is_request_authorized(headers, "wrong-key"))
        self.assertFalse(gateway.is_request_authorized({}, "secret-key"))

    def test_build_codex_request_allows_streaming_flag(self) -> None:
        gateway = load_module("openai_hub_api_gateway_stream", GATEWAY_PATH)

        payload = gateway.build_codex_chat_request(
            {
                "model": "gpt-5.4",
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertEqual(payload["model"], "gpt-5.4")
        self.assertFalse(payload["store"])

    def test_build_codex_chat_request_does_not_forward_max_output_tokens(self) -> None:
        gateway = load_module("openai_hub_api_gateway_max_tokens", GATEWAY_PATH)

        payload = gateway.build_codex_chat_request(
            {
                "model": "gpt-5.4",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

        self.assertNotIn("max_output_tokens", payload)

    def test_build_anthropic_message_response_from_codex_payload(self) -> None:
        gateway = load_module("openai_hub_api_gateway_anthropic_response", GATEWAY_PATH)
        payload = {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

        result = gateway.build_anthropic_message_response(payload, model="gpt-5.4")

        self.assertEqual(result["type"], "message")
        self.assertEqual(result["role"], "assistant")
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(result["content"][0]["text"], "hello")
        self.assertEqual(result["usage"]["input_tokens"], 10)

    def test_build_anthropic_message_response_never_returns_empty_content(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_response_empty_content", GATEWAY_PATH
        )
        payload = {
            "output": [],
            "usage": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
        }

        result = gateway.build_anthropic_message_response(payload, model="gpt-5.4")

        self.assertEqual(result["type"], "message")
        self.assertEqual(result["role"], "assistant")
        self.assertEqual(result["stop_reason"], "end_turn")
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(
            result["content"][0]["text"], gateway.EMPTY_ASSISTANT_FALLBACK_TEXT
        )

    def test_stream_anthropic_message_events_from_codex_stream(self) -> None:
        gateway = load_module("openai_hub_api_gateway_anthropic_sse", GATEWAY_PATH)
        lines = [
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":"Hel"}',
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":"lo"}',
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
        ]

        payload = b"".join(
            gateway.stream_anthropic_message_events(lines, model="gpt-5.4")
        ).decode("utf-8")

        self.assertIn("event: message_start", payload)
        self.assertIn("event: content_block_delta", payload)
        self.assertIn('"text":"Hel"', payload.replace(" ", ""))
        self.assertIn('"text":"lo"', payload.replace(" ", ""))
        self.assertIn("event: content_block_stop", payload)
        self.assertIn("event: message_stop", payload)

    def test_stream_anthropic_message_events_use_delta_text_when_completed_output_is_empty(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_sse_empty_output", GATEWAY_PATH
        )
        lines = [
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":"Hi"}',
            b"event: response.output_text.delta",
            b'data: {"type":"response.output_text.delta","delta":" there"}',
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
        ]

        payload = b"".join(
            gateway.stream_anthropic_message_events(lines, model="gpt-5.4")
        ).decode("utf-8")

        self.assertIn('"text":"Hi"', payload.replace(" ", ""))
        self.assertIn('"text":"there"', payload.replace(" ", ""))
        self.assertIn("event: content_block_delta", payload)
        self.assertIn("event: content_block_stop", payload)

    def test_stream_anthropic_message_events_never_stops_without_content_block(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_sse_empty_completion", GATEWAY_PATH
        )
        lines = [
            b"event: response.created",
            b'data: {"type":"response.created","response":{"model":"gpt-5.4"}}',
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[],"usage":{"input_tokens":3,"output_tokens":0,"total_tokens":3}}}',
        ]

        payload = b"".join(
            gateway.stream_anthropic_message_events(lines, model="gpt-5.4")
        ).decode("utf-8")
        compact = payload.replace(" ", "")

        self.assertIn("event: message_start", payload)
        self.assertIn("event: content_block_start", payload)
        self.assertIn('"type":"text"', compact)
        self.assertIn("event: content_block_delta", payload)
        self.assertIn("event: content_block_stop", payload)
        self.assertIn('"stop_reason":"end_turn"', compact)
        self.assertIn("event: message_stop", payload)

    def test_stream_anthropic_message_events_include_tool_use_blocks(self) -> None:
        gateway = load_module("openai_hub_api_gateway_anthropic_sse_tools", GATEWAY_PATH)
        lines = [
            b"event: response.completed",
            b'data: {"type":"response.completed","response":{"output":[{"type":"function_call","call_id":"toolu_1","name":"read_file","arguments":"{\\"path\\":\\"README.md\\"}"}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
        ]

        payload = b"".join(
            gateway.stream_anthropic_message_events(lines, model="gpt-5.4")
        ).decode("utf-8")

        self.assertIn('"type":"tool_use"', payload.replace(" ", ""))
        self.assertIn('"name":"read_file"', payload.replace(" ", ""))
        self.assertIn('"partial_json":"{\\"path\\":\\"README.md\\"}"', payload.replace(" ", ""))

    def test_service_lists_models_using_defaults(self) -> None:
        gateway = load_module("openai_hub_api_gateway_models", GATEWAY_PATH)
        service = gateway.LocalAPIGatewayService(root=Path("."))

        payload = service.build_models_payload()
        model_ids = [item["id"] for item in payload["data"]]

        self.assertIn(service.default_model, model_ids)

    def test_service_fallback_model_list_does_not_expose_codex_only_model(self) -> None:
        gateway = load_module("openai_hub_api_gateway_models_fallback", GATEWAY_PATH)

        class FakeSwitcher:
            ROOT = Path(".")
            TARGET_OPENCODE_MODEL_KEY = "gpt-5.4"
            TARGET_OPENCLAW_MODEL_ID = "gpt-5.4-codex"

            @staticmethod
            def load_store(_root: Path):
                return {
                    "active": "alpha",
                    "accounts": {
                        "alpha": {
                            "type": "oauth",
                            "provider": "openai-codex",
                            "access": "access-alpha",
                            "refresh": "refresh-alpha",
                            "expires": 1,
                            "accountId": "acct-alpha",
                        }
                    },
                }

            @staticmethod
            def normalize_saved_profile(profile):
                return dict(profile)

            @staticmethod
            def get_selected_alias(_root: Path):
                return "alpha"

        def fake_get(_url, headers=None, timeout=None):
            _ = (headers, timeout)
            raise RuntimeError("discovery failed")

        service = gateway.LocalAPIGatewayService(
            root=Path("."), switcher_module=FakeSwitcher, requests_get=fake_get
        )

        payload = service.build_models_payload()
        model_ids = [item["id"] for item in payload["data"]]

        self.assertEqual(model_ids, ["gpt-5.4"])

    def test_service_lists_models_using_upstream_discovery_when_available(self) -> None:
        gateway = load_module("openai_hub_api_gateway_dynamic_models", GATEWAY_PATH)

        class FakeSwitcher:
            ROOT = Path(".")
            TARGET_OPENCODE_MODEL_KEY = "gpt-5.4"
            TARGET_OPENCLAW_MODEL_ID = "gpt-5.4-codex"
            OPENCODE_CONFIG_FILE = Path("dynamic-opencode.json")

            @staticmethod
            def read_json(_path: Path):
                return {}

            @staticmethod
            def write_json(_path: Path, _data):
                return None

            @staticmethod
            def load_store(_root: Path):
                return {
                    "active": "alpha",
                    "accounts": {
                        "alpha": {
                            "type": "oauth",
                            "provider": "openai-codex",
                            "access": "access-alpha",
                            "refresh": "refresh-alpha",
                            "expires": 1,
                            "accountId": "acct-alpha",
                        }
                    },
                }

            @staticmethod
            def normalize_saved_profile(profile):
                return dict(profile)

            @staticmethod
            def get_selected_alias(_root: Path):
                return "alpha"

        class FakeProbeResponse:
            def __init__(self, status_code: int, message: str = ""):
                self.status_code = status_code
                self.text = message

            def json(self):
                if self.status_code >= 400:
                    return {"error": {"message": self.text or "unsupported"}}
                return {}

        supported = {
            "gpt-5.2",
            "gpt-5.2-codex",
            "gpt-5.3-codex",
            "gpt-5.4",
            "gpt-5.5",
        }
        attempted: list[str] = []

        def fake_post(_url, headers=None, json=None, timeout=None, stream=None):
            _ = (headers, timeout, stream)
            model = str((json or {}).get("model") or "")
            attempted.append(model)
            if model in supported:
                return FakeProbeResponse(200)
            return FakeProbeResponse(400, "model not supported")

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "opencode.json"
            FakeSwitcher.OPENCODE_CONFIG_FILE = config_path
            config_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "openai": {
                                "models": {
                                    "gpt-5.2": {"name": "GPT 5.2"},
                                    "gpt-5.4": {"name": "GPT 5.4"},
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            service = gateway.LocalAPIGatewayService(
                root=Path("."),
                switcher_module=FakeSwitcher,
                requests_post=fake_post,
            )

            payload = service.build_models_payload()
            model_ids = [item["id"] for item in payload["data"]]

        self.assertEqual(
            model_ids,
            ["gpt-5.2", "gpt-5.2-codex", "gpt-5.3-codex", "gpt-5.4", "gpt-5.5"],
        )
        self.assertIn("gpt-5.5", attempted)
        self.assertIn("gpt-5.2-codex", attempted)
        self.assertIn("gpt-5.3-codex", attempted)

    def test_model_probe_request_uses_stream_true_without_token_limit(self) -> None:
        gateway = load_module("openai_hub_api_gateway_probe_stream", GATEWAY_PATH)

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {}

        captured_json: dict[str, object] = {}
        captured_stream: dict[str, bool] = {}

        def fake_post(_url, headers=None, json=None, timeout=None, stream=None):
            captured_json.update(dict(json or {}))
            captured_stream["value"] = bool(stream)
            return FakeResponse()

        service = gateway.LocalAPIGatewayService(
            root=Path("."), requests_post=fake_post
        )
        supported = service._probe_model_support(
            {"access": "token", "accountId": "acct"}, "gpt-5.2"
        )

        self.assertTrue(supported)
        self.assertTrue(captured_stream["value"])
        self.assertEqual(captured_json["model"], "gpt-5.2")
        self.assertEqual(captured_json["stream"], True)
        self.assertNotIn("max_output_tokens", captured_json)

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

    def test_gateway_returns_sse_stream_for_chat_completions(self) -> None:
        gateway = load_module("openai_hub_api_gateway_sse", GATEWAY_PATH)

        class FakeSwitcher:
            ROOT = Path(".")

            @staticmethod
            def read_json(path: Path):
                if not path.exists():
                    return {}
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)

            @staticmethod
            def write_json(path: Path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle)

            @staticmethod
            def load_store(_root: Path):
                return {
                    "active": "alpha",
                    "accounts": {
                        "alpha": {
                            "type": "oauth",
                            "provider": "openai-codex",
                            "access": "access-alpha",
                            "refresh": "refresh-alpha",
                            "expires": 1,
                            "accountId": "acct-alpha",
                        }
                    },
                }

            @staticmethod
            def save_store(_data, _root: Path):
                return None

            @staticmethod
            def normalize_saved_profile(profile):
                return dict(profile)

            @staticmethod
            def get_selected_alias(_root: Path):
                return "alpha"

        class FakeStreamResponse:
            def __init__(self):
                self.status_code = 200
                self.text = ""

            def json(self):
                raise AssertionError("streaming response should not call json()")

            def iter_lines(self, decode_unicode=False):
                lines = [
                    b"event: response.output_text.delta",
                    b'data: {"type":"response.output_text.delta","delta":"Hello"}',
                    b"event: response.output_text.delta",
                    b'data: {"type":"response.output_text.delta","delta":" world"}',
                    b"event: response.completed",
                    b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello world"}]}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
                ]
                if decode_unicode:
                    for line in lines:
                        yield line.decode("utf-8")
                    return
                yield from lines

        def fake_post(_url, headers=None, json=None, timeout=None, stream=None):
            _ = (headers, json, timeout, stream)
            return FakeStreamResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_switcher = getattr(gateway, "SWITCHER")
            connection = None
            try:
                setattr(gateway, "SWITCHER", FakeSwitcher)
                gateway.ensure_gateway_config(root)
                gateway.set_gateway_api_key(root, "123456")
                server, runtime_config, _service = gateway.create_gateway_server(
                    root=root,
                    host="127.0.0.1",
                    port=8765,
                )
                _service.requests_post = fake_post
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
            except Exception:
                setattr(gateway, "SWITCHER", original_switcher)
                raise
            try:
                connection = http.client.HTTPConnection(
                    runtime_config["host"], int(runtime_config["port"]), timeout=5
                )
                body = json.dumps(
                    {
                        "model": "gpt-5.4",
                        "stream": True,
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                )
                connection.request(
                    "POST",
                    "/v1/chat/completions",
                    body=body,
                    headers={
                        "Authorization": "Bearer 123456",
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                payload = response.read().decode("utf-8")
            finally:
                if connection is not None:
                    connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                setattr(gateway, "SWITCHER", original_switcher)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        self.assertIn("data: [DONE]", payload)
        self.assertIn("chat.completion.chunk", payload)
        self.assertIn("Hello", payload)

    def test_gateway_accepts_anthropic_messages_route(self) -> None:
        gateway = load_module(
            "openai_hub_api_gateway_anthropic_live_route", GATEWAY_PATH
        )

        class FakeSwitcher:
            ROOT = Path(".")

            @staticmethod
            def read_json(path: Path):
                if not path.exists():
                    return {}
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)

            @staticmethod
            def write_json(path: Path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(data, handle)

            @staticmethod
            def load_store(_root: Path):
                return {
                    "active": "alpha",
                    "accounts": {
                        "alpha": {
                            "type": "oauth",
                            "provider": "openai-codex",
                            "access": "access-alpha",
                            "refresh": "refresh-alpha",
                            "expires": 1,
                            "accountId": "acct-alpha",
                        }
                    },
                }

            @staticmethod
            def save_store(_data, _root: Path):
                return None

            @staticmethod
            def normalize_saved_profile(profile):
                return dict(profile)

            @staticmethod
            def get_selected_alias(_root: Path):
                return "alpha"

        class FakeStreamResponse:
            def __init__(self):
                self.status_code = 200
                self.text = ""

            def json(self):
                raise AssertionError("streaming response should not call json()")

            def iter_lines(self, decode_unicode=False):
                lines = [
                    b"event: response.output_text.delta",
                    b'data: {"type":"response.output_text.delta","delta":"Hello"}',
                    b"event: response.completed",
                    b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Hello"}]}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}',
                ]
                if decode_unicode:
                    for line in lines:
                        yield line.decode("utf-8")
                    return
                yield from lines

        def fake_post(_url, headers=None, json=None, timeout=None, stream=None):
            _ = (headers, json, timeout, stream)
            return FakeStreamResponse()

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            original_switcher = getattr(gateway, "SWITCHER")
            connection = None
            try:
                setattr(gateway, "SWITCHER", FakeSwitcher)
                gateway.ensure_gateway_config(root)
                gateway.set_gateway_api_key(root, "123456")
                server, runtime_config, _service = gateway.create_gateway_server(
                    root=root,
                    host="127.0.0.1",
                    port=8766,
                )
                _service.requests_post = fake_post
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
            except Exception:
                setattr(gateway, "SWITCHER", original_switcher)
                raise
            try:
                connection = http.client.HTTPConnection(
                    runtime_config["host"], int(runtime_config["port"]), timeout=5
                )
                body = json.dumps(
                    {
                        "model": "gpt-5.4",
                        "max_tokens": 128,
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                )
                connection.request(
                    "POST",
                    "/v1/messages",
                    body=body,
                    headers={
                        "x-api-key": "123456",
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                payload = response.read().decode("utf-8")
            finally:
                if connection is not None:
                    connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                setattr(gateway, "SWITCHER", original_switcher)

        self.assertEqual(response.status, 200)
        self.assertIn('"type": "message"', payload)

    def test_anthropic_tool_result_reuses_tool_use_identity(self) -> None:
        gateway = load_module("openai_hub_api_gateway_anthropic_state", GATEWAY_PATH)
        service = gateway.LocalAPIGatewayService(root=Path("."))

        service.remember_anthropic_tool_use("toolu_1", "call_1")
        mapped = service.resolve_anthropic_tool_call_id("toolu_1")

        self.assertEqual(mapped, "call_1")

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
