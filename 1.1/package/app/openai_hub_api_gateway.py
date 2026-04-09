from __future__ import annotations

import importlib
import importlib.util
import re
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
DEFAULT_MODELS_URL = "https://api.openai.com/v1/models"
MODEL_DISCOVERY_CACHE_TTL_SECONDS = 300
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
        content_type = "output_text" if role == "assistant" else "input_text"
        items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
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


def _iter_sse_payloads(lines: Any):
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
        yield __import__("json").loads(data_text)


def _encode_sse_event(payload: str | Mapping[str, Any]) -> bytes:
    if isinstance(payload, str):
        data = payload
    else:
        data = __import__("json").dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n".encode("utf-8")


def stream_chat_completion_chunks(
    lines: Any,
    model: str,
    completion_id: str | None = None,
    created: int | None = None,
):
    chunk_id = str(completion_id or f"chatcmpl-{uuid.uuid4().hex}")
    chunk_created = int(created or time.time())
    yield _encode_sse_event(
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": chunk_created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        }
    )

    emitted_content = False
    completed_payload: dict[str, Any] | None = None
    for payload in _iter_sse_payloads(lines):
        event_type = str(payload.get("type") or "")
        if event_type == "response.output_text.delta":
            delta = str(payload.get("delta") or "")
            if not delta:
                continue
            emitted_content = True
            yield _encode_sse_event(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": chunk_created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            continue
        if event_type == "response.completed":
            response = payload.get("response")
            if isinstance(response, dict):
                completed_payload = response

    if isinstance(completed_payload, dict) and not emitted_content:
        text = _extract_output_text(completed_payload)
        if text:
            yield _encode_sse_event(
                {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": chunk_created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
            )

    yield _encode_sse_event(
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": chunk_created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )
    yield _encode_sse_event("[DONE]")


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
        requests_get: Any | None = None,
    ):
        self.root = Path(root)
        self.switcher = switcher_module or SWITCHER
        self.requests_post = requests_post or requests.post
        self.requests_get = requests_get or requests.get
        self.config = ensure_gateway_config(self.root)
        self.default_model = str(
            self.config.get("defaultModel")
            or getattr(self.switcher, "TARGET_OPENCODE_MODEL_KEY", "gpt-5.4")
        )
        self._model_cache_expires_at = 0.0
        self._model_cache_ids: list[str] = []

    @staticmethod
    def _normalize_model_ids(candidates: list[str]) -> list[str]:
        model_ids: list[str] = []
        for candidate in candidates:
            value = str(candidate or "").strip()
            if not value:
                continue
            if value not in model_ids:
                model_ids.append(value)
        return LocalAPIGatewayService._sort_model_ids(model_ids)

    @staticmethod
    def _sort_model_ids(model_ids: list[str]) -> list[str]:
        def sort_key(value: str) -> tuple[int, tuple[int, ...], str]:
            normalized = str(value or "").strip().lower()
            if normalized.startswith("gpt-"):
                parts = tuple(
                    int(part)
                    for part in re.findall(r"\d+", normalized[4:].split("-", 1)[0])
                )
                return (0, tuple(parts), normalized)
            return (1, (), normalized)

        return sorted(model_ids, key=sort_key)

    def _fallback_model_ids(self) -> list[str]:
        return self._normalize_model_ids([self.default_model])

    def _candidate_model_ids(self) -> list[str]:
        candidates: list[str] = [self.default_model]
        config_path = getattr(self.switcher, "OPENCODE_CONFIG_FILE", None)
        if config_path:
            try:
                payload = self.switcher.read_json(Path(config_path))
                provider = (
                    payload.get("provider") if isinstance(payload, dict) else None
                )
                openai_provider = (
                    provider.get("openai") if isinstance(provider, dict) else None
                )
                models = (
                    openai_provider.get("models")
                    if isinstance(openai_provider, dict)
                    else None
                )
                if isinstance(models, dict):
                    candidates.extend(str(key) for key in models.keys())
            except Exception:
                pass

        candidates.extend(
            [
                "gpt-5-codex",
                "gpt-5-codex-mini",
                "gpt-5.1-codex",
                "gpt-5.1-codex-mini",
                "gpt-5.1-codex-max",
                "gpt-5.2-codex",
                "gpt-5.3-codex",
            ]
        )
        for minor in range(1, 10):
            candidates.append(f"gpt-5.{minor}")
            candidates.append(f"gpt-5.{minor}-codex")
        candidates.append("gpt-5")
        return self._normalize_model_ids(candidates)

    @staticmethod
    def _probe_error_message(response: Any) -> str:
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
                return str(error.get("message") or "")
            detail = str(payload_json.get("detail") or "").strip()
            if detail:
                return detail
        return str(getattr(response, "text", "") or "").strip()

    @staticmethod
    def _probe_result_supports_model(status_code: int, message: str) -> bool:
        lowered = str(message or "").lower()
        if 200 <= int(status_code) < 300:
            return True
        unsupported_markers = [
            "not supported",
            "unsupported",
            "does not exist",
            "invalid model",
            "unknown model",
            "model_not_found",
        ]
        if any(marker in lowered for marker in unsupported_markers):
            return False
        supported_markers = [
            "usage limit has been reached",
            "rate limit",
            "temporarily unavailable",
            "overloaded",
            "capacity",
        ]
        if any(marker in lowered for marker in supported_markers):
            return True
        return False

    def _probe_model_support(self, profile: Mapping[str, Any], model: str) -> bool:
        body = {
            "model": model,
            "store": False,
            "stream": True,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "ping"}],
                }
            ],
            "instructions": "Respond with one short word.",
        }
        response = self._post_upstream(profile, body)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 401 and hasattr(self.switcher, "refresh_openai_codex_token"):
            raise GatewayHTTPError(401, "token expired")
        return self._probe_result_supports_model(
            status_code, self._probe_error_message(response)
        )

    def _discover_model_ids(self, profile: Mapping[str, Any]) -> list[str]:
        discovered: list[str] = []
        current_time = time.time()
        if current_time < self._model_cache_expires_at and self._model_cache_ids:
            return list(self._model_cache_ids)

        candidate_ids = self._candidate_model_ids()
        normalized_profile = dict(profile)
        for model in candidate_ids:
            try:
                if self._probe_model_support(normalized_profile, model):
                    discovered.append(model)
                    continue
            except GatewayHTTPError as exc:
                if exc.status_code == 401 and hasattr(
                    self.switcher, "refresh_openai_codex_token"
                ):
                    normalized_profile = self.switcher.refresh_openai_codex_token(
                        normalized_profile
                    )
                    if self._probe_model_support(normalized_profile, model):
                        discovered.append(model)
                        continue
            except Exception:
                continue

        discovered = self._normalize_model_ids(discovered)
        if discovered:
            self._model_cache_ids = list(discovered)
            self._model_cache_expires_at = (
                current_time + MODEL_DISCOVERY_CACHE_TTL_SECONDS
            )
        return discovered

    def build_models_payload(self) -> dict[str, Any]:
        model_ids = self._fallback_model_ids()
        try:
            _alias, profile = self._resolve_profile()
            discovered = self._discover_model_ids(profile)
            if discovered:
                model_ids = discovered
        except Exception:
            pass
        return {
            "object": "list",
            "data": [
                {"id": model_id, "object": "model", "owned_by": "openaihub-local"}
                for model_id in model_ids
            ],
        }

    def current_api_key(self) -> str:
        config = ensure_gateway_config(self.root)
        self.config = dict(config)
        return str(config.get("apiKey") or "")

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

    def stream_chat_completions(self, payload: Mapping[str, Any]):
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

        return stream_chat_completion_chunks(
            response.iter_lines(),
            model=str(payload.get("model") or self.default_model),
        )


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


def _write_sse_headers(handler: BaseHTTPRequestHandler, status_code: int = 200) -> None:
    handler.send_response(status_code)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()


def build_handler_class(service: LocalAPIGatewayService):
    class LocalAPIGatewayHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _require_auth(self) -> bool:
            headers = {key: value for key, value in self.headers.items()}
            if is_request_authorized(headers, service.current_api_key()):
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
                if bool(payload.get("stream")):
                    stream_iter = service.stream_chat_completions(payload)
                    _write_sse_headers(self, 200)
                    for chunk in stream_iter:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    self.close_connection = True
                    return
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
    handler = build_handler_class(service)
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
