from __future__ import annotations

import importlib
import importlib.util
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import requests


def load_switcher_module():
    if __package__:
        return importlib.import_module(f"{__package__}.openclaw_oauth_switcher")
    try:
        return importlib.import_module("openclaw_oauth_switcher")
    except ModuleNotFoundError:
        path = Path(__file__).resolve().parent / "openclaw_oauth_switcher.py"
        spec = importlib.util.spec_from_file_location("openclaw_oauth_switcher", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        import sys

        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


SWITCHER = load_switcher_module()

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8321
DEFAULT_UPSTREAM_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_API_FILE_NAME = "local-api.json"
DEFAULT_CODEX_USER_AGENT = (
    "codex_cli_rs/0.101.0 (Mac OS 26.0.1; arm64) Apple_Terminal/464"
)
DEFAULT_CODEX_VERSION = "0.101.0"

ROOT = getattr(SWITCHER, "ROOT", Path.home() / ".openaihub")
_background_server_lock = threading.Lock()
_background_server: ThreadingHTTPServer | None = None
_background_server_thread: threading.Thread | None = None
_background_server_config: dict[str, Any] | None = None


class GatewayHTTPError(Exception):
    def __init__(
        self, status_code: int, message: str, payload: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.status_code = int(status_code)
        self.payload = payload or {}


def gateway_state_file(root: Path = ROOT) -> Path:
    return Path(root) / DEFAULT_API_FILE_NAME


def gateway_base_url(config: Mapping[str, Any]) -> str:
    host = str(config.get("host") or DEFAULT_API_HOST)
    port = int(config.get("port") or DEFAULT_API_PORT)
    return f"http://{host}:{port}"


def ensure_gateway_config(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    path = gateway_state_file(root)
    data = SWITCHER.read_json(path)
    if not isinstance(data, dict):
        data = {}
    changed = False
    if not str(data.get("host") or "").strip():
        data["host"] = DEFAULT_API_HOST
        changed = True
    if not isinstance(data.get("port"), int) or int(data.get("port") or 0) <= 0:
        data["port"] = DEFAULT_API_PORT
        changed = True
    if not str(data.get("apiKey") or "").strip():
        data["apiKey"] = secrets.token_urlsafe(24)
        changed = True
    if not str(data.get("upstreamBaseUrl") or "").strip():
        data["upstreamBaseUrl"] = DEFAULT_UPSTREAM_BASE_URL
        changed = True
    default_model = getattr(SWITCHER, "TARGET_OPENCODE_MODEL_KEY", "gpt-5.4")
    if not str(data.get("defaultModel") or "").strip():
        data["defaultModel"] = default_model
        changed = True
    data["stateFile"] = str(path)
    if changed or not path.exists():
        SWITCHER.write_json(path, data)
    return data


def set_gateway_api_key(root: Path = ROOT, api_key: str = "") -> dict[str, Any]:
    normalized = str(api_key or "").strip()
    if not normalized:
        raise ValueError("API Key 不能为空")
    config = ensure_gateway_config(root)
    config["apiKey"] = normalized
    SWITCHER.write_json(gateway_state_file(root), config)
    return config


def summarize_gateway_config(
    config: Mapping[str, Any], started: bool | None = None
) -> dict[str, Any]:
    payload = {
        "host": str(config.get("host") or DEFAULT_API_HOST),
        "port": int(config.get("port") or DEFAULT_API_PORT),
        "apiKey": str(config.get("apiKey") or ""),
        "stateFile": str(config.get("stateFile") or ""),
        "url": gateway_base_url(config),
    }
    if started is not None:
        payload["started"] = bool(started)
    return payload


def is_request_authorized(headers: Mapping[str, str], api_key: str) -> bool:
    value = str(headers.get("Authorization") or headers.get("authorization") or "")
    if not value.startswith("Bearer "):
        return False
    return secrets.compare_digest(value[7:].strip(), str(api_key or ""))


def _normalize_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("text") or item.get("input_text") or item.get("content") or ""
            )
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(content or "")


def build_codex_chat_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if bool(payload.get("stream")):
        raise ValueError("暂不支持 stream=true，请先使用非流式请求")
    model = str(
        payload.get("model")
        or getattr(SWITCHER, "TARGET_OPENCODE_MODEL_KEY", "gpt-5.4")
    )
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 不能为空")
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip() or "user"
        text = _normalize_content_text(message.get("content"))
        if not text:
            continue
        if role == "system":
            instructions.append(text)
            continue
        if role not in {"user", "assistant"}:
            raise ValueError(f"暂不支持的消息角色: {role}")
        items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            }
        )
    if not items:
        raise ValueError("至少需要一条 user/assistant 消息")
    request_body: dict[str, Any] = {
        "model": model,
        "store": False,
        "input": items,
        "instructions": "\n\n".join(part for part in instructions if part).strip(),
    }
    if payload.get("max_tokens") is not None:
        request_body["max_output_tokens"] = int(payload.get("max_tokens") or 0)
    return request_body


def _extract_output_text(payload: Mapping[str, Any]) -> str:
    if str(payload.get("object") or "") == "response.compaction":
        return ""
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    response = payload.get("response")
    if isinstance(response, dict):
        nested = str(response.get("output_text") or "").strip()
        if nested:
            return nested
    candidates = []
    if isinstance(payload.get("output"), list):
        candidates.append(payload.get("output"))
    if isinstance(response, dict) and isinstance(response.get("output"), list):
        candidates.append(response.get("output"))
    for output in candidates:
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "") != "assistant":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for piece in content:
                if not isinstance(piece, dict):
                    continue
                text = str(piece.get("text") or piece.get("output_text") or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return ""


def collect_stream_response(lines: Any) -> dict[str, Any]:
    completed_response: dict[str, Any] | None = None
    text_parts: list[str] = []
    for raw_line in lines:
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = str(raw_line)
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data_text = stripped[5:].strip()
        if not data_text:
            continue
        payload = __import__("json").loads(data_text)
        event_type = str(payload.get("type") or "")
        if event_type == "response.output_text.delta":
            delta = str(payload.get("delta") or "")
            if delta:
                text_parts.append(delta)
            continue
        if event_type == "response.completed":
            response = payload.get("response")
            if isinstance(response, dict):
                completed_response = response
    if isinstance(completed_response, dict):
        return completed_response
    fallback_text = "".join(text_parts)
    return {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": fallback_text}],
            }
        ],
        "usage": {},
    }


def _extract_usage(payload: Mapping[str, Any]) -> dict[str, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        response = payload.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    completion_tokens = int(
        usage.get("output_tokens") or usage.get("completion_tokens") or 0
    )
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


class LocalAPIGatewayService:
    def __init__(
        self,
        root: Path = ROOT,
        switcher_module: Any | None = None,
        requests_post: Any | None = None,
    ):
        self.root = Path(root)
        self.switcher = switcher_module or SWITCHER
        self.requests_post = requests_post or requests.post
        self.config = ensure_gateway_config(self.root)
        self.default_model = str(
            self.config.get("defaultModel")
            or getattr(self.switcher, "TARGET_OPENCODE_MODEL_KEY", "gpt-5.4")
        )

    def build_models_payload(self) -> dict[str, Any]:
        model_ids: list[str] = []
        for candidate in [
            self.default_model,
            getattr(self.switcher, "TARGET_OPENCLAW_MODEL_ID", ""),
        ]:
            value = str(candidate or "").strip()
            if value and value not in model_ids:
                model_ids.append(value)
        return {
            "object": "list",
            "data": [
                {"id": model_id, "object": "model", "owned_by": "openaihub-local"}
                for model_id in model_ids
            ],
        }

    def _load_store(self) -> dict[str, Any]:
        store = self.switcher.load_store(self.root)
        return store if isinstance(store, dict) else {}

    def _save_profile(self, alias: str, profile: Mapping[str, Any]) -> None:
        store = self._load_store()
        accounts = store.setdefault("accounts", {})
        accounts[alias] = {**accounts.get(alias, {}), **dict(profile)}
        self.switcher.save_store(store, self.root)

    def _resolve_profile(self) -> tuple[str, dict[str, Any]]:
        store = self._load_store()
        accounts = store.get("accounts", {})
        if not isinstance(accounts, dict) or not accounts:
            raise ValueError("当前没有可用账号，请先添加 GPT 账号")

        current_alias = None
        if hasattr(self.switcher, "get_selected_alias"):
            current_alias = self.switcher.get_selected_alias(self.root)
        if not current_alias:
            current_alias = store.get("active")

        if hasattr(self.switcher, "build_dashboard_rows") and hasattr(
            self.switcher, "apply_auto_switch_if_needed"
        ):
            try:
                rows = self.switcher.build_dashboard_rows(root=self.root)
                state = self.switcher.DashboardState(rows=rows)
                picked = self.switcher.apply_auto_switch_if_needed(
                    state,
                    current_alias=current_alias,
                    root=self.root,
                )
                if picked:
                    current_alias = picked
                    store = self._load_store()
                    accounts = store.get("accounts", {})
            except Exception:
                pass

        resolved_alias = str(current_alias or "").strip()
        if not resolved_alias or resolved_alias not in accounts:
            resolved_alias = next(iter(accounts.keys()))
        profile = accounts.get(resolved_alias)
        if not isinstance(profile, dict):
            raise ValueError("当前账号配置无效")
        if hasattr(self.switcher, "normalize_saved_profile"):
            profile = self.switcher.normalize_saved_profile(profile)
        else:
            profile = dict(profile)
        return resolved_alias, profile

    def _build_upstream_headers(self, profile: Mapping[str, Any]) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {profile.get('access', '')}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_CODEX_USER_AGENT,
            "Version": DEFAULT_CODEX_VERSION,
            "Originator": "codex_cli_rs",
            "Session_id": uuid.uuid4().hex,
        }
        account_id = str(profile.get("accountId") or "").strip()
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id
        return headers

    def _post_upstream(self, profile: Mapping[str, Any], body: Mapping[str, Any]):
        url = str(
            self.config.get("upstreamBaseUrl") or DEFAULT_UPSTREAM_BASE_URL
        ).rstrip("/")
        return self.requests_post(
            f"{url}/responses",
            headers={
                **self._build_upstream_headers(profile),
                "Accept": "text/event-stream",
            },
            json=dict(body),
            timeout=120,
            stream=True,
        )

    def handle_chat_completions(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        alias, profile = self._resolve_profile()
        body = build_codex_chat_request(payload)
        body["model"] = str(payload.get("model") or self.default_model)
        body["stream"] = True

        response = self._post_upstream(profile, body)
        if int(getattr(response, "status_code", 0) or 0) == 401:
            profile = self.switcher.refresh_openai_codex_token(profile)
            self._save_profile(alias, profile)
            response = self._post_upstream(profile, body)

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code < 200 or status_code >= 300:
            message = "上游请求失败"
            payload_json: dict[str, Any] | None = None
            try:
                parsed_json = response.json()
                if isinstance(parsed_json, dict):
                    payload_json = parsed_json
            except Exception:
                payload_json = None
            if isinstance(payload_json, dict):
                error = payload_json.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or message)
                elif str(payload_json.get("detail") or "").strip():
                    message = str(payload_json.get("detail") or message)
            elif str(getattr(response, "text", "") or "").strip():
                message = str(getattr(response, "text", "") or "").strip()
            raise GatewayHTTPError(
                status_code or 500,
                message,
                payload_json if isinstance(payload_json, dict) else {},
            )

        payload_json = collect_stream_response(response.iter_lines())

        text = _extract_output_text(
            payload_json if isinstance(payload_json, dict) else {}
        )
        usage = _extract_usage(payload_json if isinstance(payload_json, dict) else {})
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": str(payload.get("model") or self.default_model),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }


def _read_request_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    return __import__("json").loads(raw.decode("utf-8"))


def _write_json(
    handler: BaseHTTPRequestHandler, status_code: int, payload: Mapping[str, Any]
) -> None:
    body = __import__("json").dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def build_handler_class(service: LocalAPIGatewayService, api_key: str):
    class LocalAPIGatewayHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _require_auth(self) -> bool:
            headers = {key: value for key, value in self.headers.items()}
            if is_request_authorized(headers, api_key):
                return True
            _write_json(self, 401, {"error": {"message": "unauthorized"}})
            return False

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                _write_json(self, 200, {"status": "ok"})
                return
            if not self._require_auth():
                return
            if parsed.path == "/v1/models":
                _write_json(self, 200, service.build_models_payload())
                return
            _write_json(self, 404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._require_auth():
                return
            if parsed.path != "/v1/chat/completions":
                _write_json(self, 404, {"error": {"message": "not found"}})
                return
            try:
                payload = _read_request_json(self)
                result = service.handle_chat_completions(payload)
                _write_json(self, 200, result)
            except GatewayHTTPError as exc:
                _write_json(self, exc.status_code, {"error": {"message": str(exc)}})
            except Exception as exc:
                _write_json(self, 400, {"error": {"message": str(exc)}})

    return LocalAPIGatewayHandler


def create_gateway_server(
    root: Path = ROOT,
    host: str | None = None,
    port: int | None = None,
) -> tuple[ThreadingHTTPServer, dict[str, Any], LocalAPIGatewayService]:
    config = ensure_gateway_config(root)
    if host:
        config["host"] = str(host)
    if port:
        config["port"] = int(port)
    config["stateFile"] = str(gateway_state_file(root))
    SWITCHER.write_json(gateway_state_file(root), config)
    service = LocalAPIGatewayService(root=root)
    service.config = config
    handler = build_handler_class(service, str(config.get("apiKey") or ""))
    resolved_host = str(config.get("host") or DEFAULT_API_HOST)
    resolved_port = int(config.get("port") or DEFAULT_API_PORT)
    server = ThreadingHTTPServer((resolved_host, resolved_port), handler)
    return server, config, service


def ensure_background_gateway_running(root: Path = ROOT) -> dict[str, Any]:
    global _background_server, _background_server_thread, _background_server_config
    root = Path(root)
    with _background_server_lock:
        config = ensure_gateway_config(root)
        thread_alive = (
            _background_server_thread is not None
            and _background_server_thread.is_alive()
        )
        same_target = False
        if thread_alive and isinstance(_background_server_config, dict):
            same_target = str(_background_server_config.get("host") or "") == str(
                config.get("host") or ""
            ) and int(_background_server_config.get("port") or 0) == int(
                config.get("port") or 0
            )
        if thread_alive and same_target:
            return summarize_gateway_config(config, started=False)

        server, config, _service = create_gateway_server(root=root)
        thread = threading.Thread(
            target=server.serve_forever,
            name="openaihub-local-api",
            daemon=True,
        )
        thread.start()
        _background_server = server
        _background_server_thread = thread
        _background_server_config = dict(config)
        return summarize_gateway_config(config, started=True)


def serve_local_api_gateway(
    root: Path = ROOT,
    host: str | None = None,
    port: int | None = None,
) -> int:
    server, config, _service = create_gateway_server(root=root, host=host, port=port)
    print("本地 API 网关已启动")
    print(f"- 地址：{gateway_base_url(config)}")
    print(f"- API Key：{config['apiKey']}")
    print(f"- 状态文件：{config['stateFile']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
