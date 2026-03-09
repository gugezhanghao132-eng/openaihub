#!/usr/bin/env python3
import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import inspect
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
import re
import secrets
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape as escape_rich_markup
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    import termios
    import tty
except ImportError:
    termios = None
    tty = None


ROOT = Path.home() / ".openclaw"
AGENTS_ROOT = ROOT / "agents"
STORE_FILE = ROOT / "openai-codex-accounts.json"
APP_STATE_FILE = ROOT / "openai-hub-state.json"
OPENCODE_CONFIG_ROOT = Path.home() / ".config" / "opencode"
OPENCODE_CONFIG_FILE = OPENCODE_CONFIG_ROOT / "opencode.json"
OPENCODE_STATE_ROOT = Path.home() / ".local" / "share" / "opencode"
OPENCODE_AUTH_FILE = OPENCODE_STATE_ROOT / "auth.json"
AUDIT_LOG_DIR = ROOT / "logs"
SWITCH_AUDIT_LOG_FILE = AUDIT_LOG_DIR / "switch-events.jsonl"
PROFILE_KEY = "openai-codex:default"
PROVIDER_KEY = "openai-codex"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TOKEN_URL = "https://auth.openai.com/oauth/token"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_SCOPE = "openid profile email offline_access"
JsonDict = dict[str, Any]
SCRIPT_DIR = (
    Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
VERSION_FILE = SCRIPT_DIR.parent / "version.txt"
LOGIN_HELPER = SCRIPT_DIR / "openai_codex_login_helper.mjs"
BUNDLED_RUNTIME_DIR = SCRIPT_DIR / "runtime"
BUNDLED_NODE_EXE = (
    BUNDLED_RUNTIME_DIR / "node" / ("node.exe" if os.name == "nt" else "node")
)
BUNDLED_OPENCLAW_ENTRY = (
    BUNDLED_RUNTIME_DIR / "node_modules" / "openclaw" / "openclaw.mjs"
)
BUNDLED_OPENAI_CODEX_HELPER_ENTRY = BUNDLED_RUNTIME_DIR / "oauth" / "openai-codex.js"
BUNDLED_OPENCODE_EXE = BUNDLED_RUNTIME_DIR / (
    "opencode.exe" if os.name == "nt" else "opencode"
)
console = Console()
APP_NAME = "OpenAI Hub"


def load_app_release_version() -> str:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8-sig").strip()
        if value:
            return value
    except OSError:
        pass
    return "dev"


APP_RELEASE_VERSION = load_app_release_version()
APP_VARIANT = os.environ.get("GT_VARIANT", "full").strip().lower() or "full"
HOME_PANEL_TITLE = "账号中心"
PANEL_CONTENT_WIDTH = 72
PANEL_WIDTH = PANEL_CONTENT_WIDTH + 4
DEFAULT_WINDOW_COLS = 80
DEFAULT_WINDOW_LINES = 33
TARGET_OPENCLAW_MODEL_ID = "gpt-5.4-codex"
TARGET_OPENCLAW_MODEL_NAME = "GPT-5.4 Codex"
TARGET_OPENCLAW_MODEL_ALIAS = "gpt54"
TARGET_OPENCODE_MODEL_KEY = "gpt-5.4"
TARGET_OPENCODE_MODEL_NAME = "GPT 5.4 (OAuth)"
INIT_VERSION = "local-init-v1"
AUTO_REFRESH_INTERVAL_MS = 180 * 1000
MENU_IDLE_TICK_MS = 60
DASHBOARD_REQUEST_TIMEOUT_SECONDS = 20
DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS = 3
DASHBOARD_AUTH_HARD_FAILURE_COOLDOWN_MS = 15 * 60 * 1000
DASHBOARD_MAX_BACKGROUND_REFRESHES_PER_CYCLE = 1
DASHBOARD_DAILY_FULL_REFRESH_MS = 24 * 60 * 60 * 1000
DASHBOARD_7D_RESET_REFRESH_THRESHOLD_MS = 24 * 60 * 60 * 1000
DASHBOARD_5H_LOW_REFRESH_THRESHOLD = 50.0
MONITOR_FRAME_STEP = 5
STEP_LOG_DELAY_SECONDS = 0.12
SEVEN_DAY_PERCENT_PER_FULL_5H = 30.0
MAX_DASHBOARD_FETCH_WORKERS = 4
MONITOR_FRAMES = (
    "[#0f172a]•[/][#38bdf8]•[/][#0f172a]•[/]",
    "[#0f172a]•[/][#0f172a]•[/][#38bdf8]•[/]",
    "[#0f172a]•[/][#38bdf8]•[/][#0f172a]•[/]",
    "[#38bdf8]•[/][#0f172a]•[/][#0f172a]•[/]",
)


def build_refresh_bar_frames() -> tuple[str, ...]:
    trail = ["#38bdf8", "#60a5fa", "#93c5fd", "#334155", "#1e293b", "#0f172a"]
    track_length = 5
    frames: list[str] = []
    for head in range(-len(trail), track_length + 1):
        cells = ["[#0f172a]·[/]" for _ in range(track_length)]
        for offset, color in enumerate(trail):
            pos = head - offset
            if 0 <= pos < track_length:
                cells[pos] = f"[{color}]■[/]"
        frames.append("".join(cells))
    for head in range(track_length + len(trail) - 1, -len(trail) - 1, -1):
        cells = ["[#0f172a]·[/]" for _ in range(track_length)]
        for offset, color in enumerate(trail):
            pos = head - offset
            if 0 <= pos < track_length:
                cells[pos] = f"[{color}]■[/]"
        frames.append("".join(cells))
    return tuple(frames)


REFRESH_BAR_FRAMES = build_refresh_bar_frames()


def variant_is_openclaw() -> bool:
    return APP_VARIANT in {"full", "openclaw"}


def variant_is_opencode() -> bool:
    return APP_VARIANT in {"full", "opencode"}


def variant_requires_openclaw_login() -> bool:
    return APP_VARIANT in {"full", "openclaw", "opencode"}


def variant_requires_opencode_config() -> bool:
    return APP_VARIANT in {"full", "opencode"}


stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8")
stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
if callable(stderr_reconfigure):
    stderr_reconfigure(encoding="utf-8")


def hide_cursor(stream: TextIO | None = None) -> None:
    target = stream or sys.stdout
    if stream is None and not target.isatty():
        return
    target.write("\x1b[?25l")
    target.flush()


def show_cursor(stream: TextIO | None = None) -> None:
    target = stream or sys.stdout
    if stream is None and not target.isatty():
        return
    target.write("\x1b[?25h")
    target.flush()


@contextmanager
def raw_stdin_mode() -> Iterator[None]:
    if os.name == "nt" or not sys.stdin.isatty() or termios is None or tty is None:
        yield
        return
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


@contextmanager
def hidden_cursor(stream: TextIO | None = None) -> Iterator[None]:
    hide_cursor(stream)
    try:
        yield
    finally:
        show_cursor(stream)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def read_json(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_jsonl(path: Path, data: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.write("\n")


def backup(path: Path) -> Path:
    bak = path.with_name(f"{path.name}.bak-switch-{ts()}")
    shutil.copy2(path, bak)
    return bak


def write_json_with_backup(path: Path, data: JsonDict) -> None:
    if path.exists():
        backup(path)
    write_json(path, data)


def deep_copy_json(data: JsonDict) -> JsonDict:
    return copy.deepcopy(data)


def ensure_model_entry(
    models: list[JsonDict], target_id: str, factory: Callable[[], JsonDict]
) -> bool:
    if any(
        str(item.get("id") or "") == target_id
        for item in models
        if isinstance(item, dict)
    ):
        return False
    models.append(factory())
    return True


def ensure_named_model_entry(
    models: JsonDict, target_key: str, factory: Callable[[], JsonDict]
) -> bool:
    if isinstance(models.get(target_key), dict):
        return False
    models[target_key] = factory()
    return True


def build_default_openclaw_model_entry() -> JsonDict:
    return {
        "id": TARGET_OPENCLAW_MODEL_ID,
        "name": TARGET_OPENCLAW_MODEL_NAME,
        "input": ["text", "image"],
        "contextWindow": 200000,
        "maxTokens": 32000,
        "reasoning": False,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "api": "openai-completions",
    }


def build_default_opencode_model_entry() -> JsonDict:
    return {
        "name": TARGET_OPENCODE_MODEL_NAME,
        "limit": {"context": 272000, "output": 128000},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
    }


def clone_openclaw_model_entry(template: JsonDict | None) -> JsonDict:
    cloned = (
        deep_copy_json(template)
        if isinstance(template, dict)
        else build_default_openclaw_model_entry()
    )
    cloned["id"] = TARGET_OPENCLAW_MODEL_ID
    cloned["name"] = TARGET_OPENCLAW_MODEL_NAME
    return cloned


def clone_opencode_model_entry(template: JsonDict | None) -> JsonDict:
    cloned = (
        deep_copy_json(template)
        if isinstance(template, dict)
        else build_default_opencode_model_entry()
    )
    cloned["name"] = TARGET_OPENCODE_MODEL_NAME
    return cloned


def mask(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 12:
        return value[:3] + "***"
    return value[:6] + "..." + value[-6:]


def format_reset_at(reset_at_ms: int | None, now_ms: int | None = None) -> str:
    if not reset_at_ms:
        return "未知"
    base_ms = now_ms if now_ms is not None else current_time_ms()
    remaining_ms = max(0, int(reset_at_ms) - int(base_ms))
    total_minutes = remaining_ms // 60000
    total_hours = total_minutes // 60
    days = total_hours // 24
    hours = total_hours % 24
    minutes = total_minutes % 60
    if days > 0:
        return f"{days}天{hours}小时"
    if total_hours > 0:
        return f"{total_hours}小时{minutes}分钟"
    if total_minutes > 0:
        return f"{total_minutes}分钟"
    return "即将重置"


def current_local_day_key(now_ms: int | None = None) -> str:
    if now_ms is None:
        return datetime.now().date().isoformat()
    return datetime.fromtimestamp(int(now_ms) / 1000).date().isoformat()


def clear_screen() -> None:
    console.clear()
    hide_cursor()


@dataclass
class DashboardState:
    rows: list[JsonDict] = field(default_factory=list)
    dirty: bool = True
    monitoring_enabled: bool = True
    auto_refresh_interval_ms: int = AUTO_REFRESH_INTERVAL_MS
    last_refresh_at_ms: int | None = None
    last_refresh_error: str | None = None
    is_refreshing: bool = False
    refresh_message: str = "刷新中"
    refresh_frame_index: int = 0
    monitor_frame_index: int = 0
    monitor_frame_tick: int = 0
    pending_refresh_thread: threading.Thread | None = None
    pending_refresh_rows: list[JsonDict] | None = None
    pending_refresh_error: Exception | None = None


def build_main_menu_options() -> list[JsonDict]:
    return [
        {"key": "add", "label": "登录账号"},
        {"key": "overview", "label": "账号总览"},
        {"key": "switch", "label": "切换账号"},
        {"key": "rename", "label": "修改名称"},
        {"key": "remove", "label": "删除账号"},
        {"key": "refresh", "label": "刷新状态"},
        {"key": "exit", "label": "退出程序"},
    ]


def render_dashboard_text(
    rows: list[JsonDict], current_alias: str, include_header: bool = True
) -> str:
    divider = f"[dim]{'─' * 64}[/dim]"
    safe_current_alias = escape_panel_text(current_alias)
    lines: list[str] = []
    if include_header:
        lines.extend(
            [
                "[bold cyan]账号中心[/bold cyan]",
                f"[dim]当前账号[/dim] [bold white]{safe_current_alias}[/bold white]",
                f"[dim]账号总数[/dim] [bold]{len(rows)}[/bold]",
                "",
            ]
        )
    if not rows:
        lines.append("[dim]还没有保存任何账号。[/dim]")
    for index, row in enumerate(rows):
        if index > 0:
            lines.extend([divider, ""])
        marker = (
            "[bold cyan][当前][/bold cyan]" if row["isCurrent"] else "[dim][待命][/dim]"
        )
        display_name = escape_panel_text(str(row.get("displayName") or row["alias"]))
        account_id = escape_panel_text(str(row.get("accountId") or "未知"))
        status = classify_dashboard_row(row)
        colored_name = (
            f"[{status['style']}][bold]{display_name}[/bold][/{status['style']}]"
        )
        last_synced_at = format_dashboard_last_synced_at(row.get("_lastRefreshedAtMs"))
        sync_issue_suffix = format_dashboard_sync_issue_suffix(row)
        lines.append(
            f"{marker} {colored_name} [dim]·[/dim] [dim]账号ID[/dim] {account_id} [dim]·[/dim] [dim]上次同步[/dim] {last_synced_at}{sync_issue_suffix}"
        )
        windows = row.get("windows") or []
        if not windows:
            lines.append("  [dim]暂无额度数据[/dim]")
            continue
        for window in windows:
            used = float(window.get("usedPercent", 0))
            remaining = max(0.0, 100.0 - used)
            quota_style = quota_style_name(remaining)
            bar = colorize_progress_bar(progress_bar(used), quota_style)
            lines.append(
                f"  [bold]{window.get('label', '?')}[/bold] {bar} [dim]已用[/dim] {used:.1f}% [dim]·[/dim] [{quota_style}]剩余 {remaining:.1f}%[/{quota_style}] [dim]·[/dim] [dim]{format_reset_at(window.get('resetAt'))}[/dim]"
            )
    return "\n".join(lines)


def format_dashboard_last_synced_at(last_refreshed_at_ms: Any) -> str:
    if not isinstance(last_refreshed_at_ms, int) or last_refreshed_at_ms <= 0:
        return "未同步"
    synced_at = datetime.fromtimestamp(int(last_refreshed_at_ms) / 1000)
    now = datetime.now()
    if synced_at.date() == now.date():
        return synced_at.strftime("今天 %H:%M")
    return synced_at.strftime("%m-%d %H:%M")


def format_dashboard_sync_issue_suffix(row: JsonDict) -> str:
    issue = describe_dashboard_issue(row)
    if issue is None:
        return ""
    style = str(issue.get("style") or "yellow")
    status_code = int(row.get("_authIssueStatus") or 0)
    if status_code == 401:
        return " [dim]·[/dim] [yellow]401 可能网络/鉴权[/yellow]"
    if status_code == 403:
        return " [dim]·[/dim] [yellow]403 可能网络/工作组[/yellow]"
    issue_key = str(issue.get("key") or "")
    if issue_key == "expired":
        return " [dim]·[/dim] [red]401 可能网络/鉴权[/red]"
    if issue_key == "workspace":
        return " [dim]·[/dim] [red]403 可能网络/工作组[/red]"
    detail = str(issue.get("detail") or "")
    if "请求超时" in detail or "连接超时" in detail:
        return f" [dim]·[/dim] [{style}]请求超时[/{style}]"
    if "网络连接失败" in detail or "VPN" in detail or "代理" in detail:
        return f" [dim]·[/dim] [{style}]网络波动[/{style}]"
    if "暂停自动检测" in detail:
        return " [dim]·[/dim] [yellow]需重登[/yellow]"
    if issue_key == "warning":
        return f" [dim]·[/dim] [{style}]同步异常[/{style}]"
    if issue_key == "error":
        return f" [dim]·[/dim] [{style}]状态异常[/{style}]"
    return f" [dim]·[/dim] [{style}]{escape_panel_text(str(issue.get('label') or '异常'))}[/{style}]"


def get_window_remaining_map(windows: list[JsonDict]) -> dict[str, float]:
    remaining: dict[str, float] = {}
    for window in windows:
        label = str(window.get("label", "") or "").strip().lower()
        if not label:
            continue
        used = max(0.0, min(100.0, float(window.get("usedPercent", 0) or 0)))
        remaining[label] = max(0.0, 100.0 - used)
    return remaining


def get_window_remaining_value(row: JsonDict, label: str) -> float | None:
    remaining = get_window_remaining_map(row.get("windows") or [])
    normalized_label = label.strip().lower()
    return remaining.get(normalized_label)


def get_required_7d_remaining_for_5h(remaining_5h: float | None) -> float | None:
    if remaining_5h is None:
        return None
    return max(0.0, float(remaining_5h) * (SEVEN_DAY_PERCENT_PER_FULL_5H / 100.0))


def get_effective_5h_remaining_percent(row: JsonDict) -> float | None:
    remaining_5h = get_window_remaining_value(row, "5h")
    remaining_7d = get_window_remaining_value(row, "7d")
    if remaining_5h is None:
        return None
    if remaining_7d is None:
        return float(remaining_5h)
    supported_5h_by_7d = float(remaining_7d) * (100.0 / SEVEN_DAY_PERCENT_PER_FULL_5H)
    return max(0.0, min(float(remaining_5h), supported_5h_by_7d))


def get_window_reset_at_ms(row: JsonDict, label: str) -> int | None:
    normalized_label = label.strip().lower()
    for window in row.get("windows") or []:
        if str(window.get("label") or "").strip().lower() != normalized_label:
            continue
        reset_at = window.get("resetAt")
        return int(reset_at) if isinstance(reset_at, int) else None
    return None


def compute_dashboard_row_next_refresh_at(
    row: JsonDict, is_current: bool, now_ms: int | None = None
) -> int:
    now = current_time_ms() if now_ms is None else int(now_ms)
    if is_current:
        return now + AUTO_REFRESH_INTERVAL_MS

    blocked_until = int(row.get("_authBlockedUntilMs") or 0)
    if blocked_until > now:
        return blocked_until

    remaining_5h = get_window_remaining_value(row, "5h")
    reset_7d = get_window_reset_at_ms(row, "7d")
    daily_success_day = str(row.get("_dailyRefreshSuccessDay") or "")
    if daily_success_day != current_local_day_key(now):
        return now

    if (
        isinstance(reset_7d, int)
        and reset_7d - now <= DASHBOARD_7D_RESET_REFRESH_THRESHOLD_MS
    ):
        return now + AUTO_REFRESH_INTERVAL_MS
    if (
        remaining_5h is not None
        and float(remaining_5h) < DASHBOARD_5H_LOW_REFRESH_THRESHOLD
    ):
        return now + AUTO_REFRESH_INTERVAL_MS
    if isinstance(reset_7d, int):
        return max(
            now + AUTO_REFRESH_INTERVAL_MS,
            reset_7d - DASHBOARD_7D_RESET_REFRESH_THRESHOLD_MS,
        )
    return now + DASHBOARD_DAILY_FULL_REFRESH_MS


def get_dashboard_row_refresh_priority(row: JsonDict) -> tuple[int, float, int]:
    today_key = current_local_day_key()
    if str(row.get("_dailyRefreshSuccessDay") or "") != today_key:
        attempted_today = str(row.get("_dailyRefreshAttemptDay") or "") == today_key
        return (
            0 if not attempted_today else 1,
            0.0,
            int(row.get("_dailyRefreshAttemptAtMs") or 0),
        )
    if row.get("error"):
        return (2, -1.0, 0)
    if row.get("warning"):
        return (3, -1.0, 0)
    remaining_5h = get_window_remaining_value(row, "5h")
    remaining_7d = get_window_remaining_value(row, "7d")
    lowest_remaining = min(
        [value for value in (remaining_5h, remaining_7d) if value is not None],
        default=100.0,
    )
    return (
        4,
        float(lowest_remaining),
        int(get_window_reset_at_ms(row, "7d") or 10**18),
    )


def does_row_7d_cover_remaining_5h(row: JsonDict) -> bool:
    remaining_7d = get_window_remaining_value(row, "7d")
    required_7d = get_required_7d_remaining_for_5h(
        get_window_remaining_value(row, "5h")
    )
    if remaining_7d is None or required_7d is None:
        return False
    return float(remaining_7d) >= float(required_7d)


def get_auto_switch_candidate_score(row: JsonDict) -> tuple[float, float, str]:
    remaining_5h = get_effective_5h_remaining_percent(row)
    remaining_7d = get_window_remaining_value(row, "7d")
    return (
        float(remaining_5h if remaining_5h is not None else -1.0),
        float(remaining_7d if remaining_7d is not None else -1.0),
        str(row.get("alias") or ""),
    )


def get_auto_switch_fallback_score(row: JsonDict) -> tuple[float, float, str]:
    remaining_5h = get_effective_5h_remaining_percent(row)
    remaining_7d = get_window_remaining_value(row, "7d")
    return (
        float(remaining_5h if remaining_5h is not None else -1.0),
        float(remaining_7d if remaining_7d is not None else -1.0),
        str(row.get("alias") or ""),
    )


def row_has_auth_issue_warning(row: JsonDict) -> bool:
    if int(row.get("_authIssueCount") or 0) > 0:
        return True
    warning_text = str(row.get("warning") or "")
    return "401" in warning_text or "403" in warning_text


def can_row_participate_in_auto_switch(row: JsonDict) -> bool:
    if row.get("error"):
        return False
    if row_has_auth_issue_warning(row):
        return False
    return bool(row.get("alias"))


def is_row_7d_healthy_for_auto_switch(row: JsonDict, min_7d_remaining: float) -> bool:
    if not can_row_participate_in_auto_switch(row):
        return False
    remaining_7d = get_window_remaining_value(row, "7d")
    if remaining_7d is None:
        return False
    return float(remaining_7d) >= float(min_7d_remaining)


def is_row_safe_for_auto_switch(
    row: JsonDict, min_5h_remaining: float, min_7d_remaining: float
) -> bool:
    if not is_row_7d_healthy_for_auto_switch(row, min_7d_remaining):
        return False
    remaining_5h = get_window_remaining_value(row, "5h")
    if remaining_5h is None:
        return False
    return float(remaining_5h) >= float(min_5h_remaining)


def can_keep_current_account_until_zero(row: JsonDict) -> bool:
    if row.get("error"):
        return False
    remaining_7d = get_window_remaining_value(row, "7d")
    remaining_5h = get_window_remaining_value(row, "5h")
    if remaining_7d is None or remaining_5h is None:
        return False
    return float(remaining_7d) > 0.0 and float(remaining_5h) > 0.0


def summarize_auto_switch_row(row: JsonDict | None) -> JsonDict | None:
    if not isinstance(row, dict):
        return None
    return {
        "alias": str(row.get("alias") or ""),
        "displayName": str(row.get("displayName") or ""),
        "accountId": str(row.get("accountId") or ""),
        "remaining5h": get_window_remaining_value(row, "5h"),
        "effective5h": get_effective_5h_remaining_percent(row),
        "remaining7d": get_window_remaining_value(row, "7d"),
        "required7dFor5h": get_required_7d_remaining_for_5h(
            get_window_remaining_value(row, "5h")
        ),
        "coversRemaining5h": does_row_7d_cover_remaining_5h(row),
        "error": str(row.get("error") or "") or None,
        "warning": str(row.get("warning") or "") or None,
    }


def build_auto_switch_decision(
    rows: list[JsonDict],
    current_alias: str | None = None,
    min_5h_remaining: float = 5.0,
    min_7d_remaining: float = 5.0,
) -> JsonDict | None:
    if not rows:
        return None

    resolved_current_alias = current_alias or next(
        (
            str(row.get("alias") or "")
            for row in rows
            if row.get("isCurrent") and row.get("alias")
        ),
        "",
    )
    current_row = next(
        (row for row in rows if str(row.get("alias") or "") == resolved_current_alias),
        next((row for row in rows if row.get("isCurrent")), None),
    )
    if current_row is None:
        return None

    current_remaining_7d = get_window_remaining_value(current_row, "7d")
    current_remaining_5h = get_window_remaining_value(current_row, "5h")
    current_reason = "current-below-threshold"
    if current_row.get("error"):
        current_reason = "current-error"
    elif current_remaining_7d is None or current_remaining_5h is None:
        current_reason = "current-missing-quota"
    elif float(current_remaining_7d) < float(min_7d_remaining):
        current_reason = "current-7d-below-threshold"
    elif float(current_remaining_5h) < float(min_5h_remaining):
        current_reason = "current-5h-below-threshold"
    else:
        return None

    other_rows = [
        row
        for row in rows
        if str(row.get("alias") or "") != str(current_row.get("alias") or "")
        and can_row_participate_in_auto_switch(row)
    ]
    if not other_rows:
        return None

    safe_rows = [
        row
        for row in other_rows
        if is_row_safe_for_auto_switch(row, min_5h_remaining, min_7d_remaining)
    ]
    if safe_rows:
        picked = max(safe_rows, key=get_auto_switch_candidate_score)
        reason_code = f"{current_reason}-picked-best-safe-candidate"
    else:
        if can_keep_current_account_until_zero(current_row):
            return None
        picked = max(other_rows, key=get_auto_switch_fallback_score)
        reason_code = (
            f"{current_reason}-picked-best-fallback-candidate-after-current-zero"
        )
    return {
        "pickedAlias": str(picked.get("alias") or "") or None,
        "reasonCode": reason_code,
        "thresholds": {
            "min5hRemaining": float(min_5h_remaining),
            "min7dRemaining": float(min_7d_remaining),
            "sevenDayPercentPerFull5h": float(SEVEN_DAY_PERCENT_PER_FULL_5H),
        },
        "current": summarize_auto_switch_row(current_row),
        "picked": summarize_auto_switch_row(picked),
        "candidates": [summarize_auto_switch_row(row) for row in other_rows],
    }


def pick_auto_switch_alias(
    rows: list[JsonDict],
    current_alias: str | None = None,
    min_5h_remaining: float = 5.0,
    min_7d_remaining: float = 5.0,
) -> str | None:
    decision = build_auto_switch_decision(
        rows,
        current_alias=current_alias,
        min_5h_remaining=min_5h_remaining,
        min_7d_remaining=min_7d_remaining,
    )
    if not isinstance(decision, dict):
        return None
    return str(decision.get("pickedAlias") or "") or None


def apply_auto_switch_if_needed(
    state: DashboardState,
    switch_alias_fn: Callable[..., int] | None = None,
    refresh_rows_fn: Callable[[DashboardState, Path], list[JsonDict]] | None = None,
    current_alias: str | None = None,
    min_5h_remaining: float = 5.0,
    min_7d_remaining: float = 5.0,
    root: Path = ROOT,
) -> str | None:
    resolved_switch_alias_fn = switch_alias_fn or switch_alias
    resolved_refresh_rows_fn = refresh_rows_fn or refresh_dashboard_rows_from_store
    decision = build_auto_switch_decision(
        state.rows,
        current_alias=current_alias,
        min_5h_remaining=min_5h_remaining,
        min_7d_remaining=min_7d_remaining,
    )
    if not isinstance(decision, dict):
        return None
    picked_alias = str(decision.get("pickedAlias") or "") or None
    if not picked_alias:
        return None
    resolved_switch_alias_fn(
        root,
        picked_alias,
        audit_event={
            "action": "account-switch",
            "mode": "auto",
            "reasonCode": str(decision.get("reasonCode") or "auto-switch"),
            "thresholds": decision.get("thresholds"),
            "currentSnapshot": decision.get("current"),
            "pickedSnapshot": decision.get("picked"),
            "candidates": decision.get("candidates"),
        },
    )
    resolved_refresh_rows_fn(state, root)
    return picked_alias


def describe_dashboard_issue(row: JsonDict) -> JsonDict | None:
    error_text = str(row.get("error", "") or "").strip()
    if error_text:
        normalized = error_text.lower()
        if "401" in normalized or "登录态已失效" in error_text:
            return {
                "key": "expired",
                "label": "账号已过期",
                "detail": error_text,
                "style": "red",
            }
        if "403" in normalized or "工作组" in error_text:
            return {
                "key": "workspace",
                "label": "工作组异常",
                "detail": error_text,
                "style": "red",
            }
        return {
            "key": "error",
            "label": "状态异常",
            "detail": error_text,
            "style": "red",
        }
    warning_text = str(row.get("warning", "") or "").strip()
    if warning_text:
        return {
            "key": "warning",
            "label": "沿用上次数据",
            "detail": warning_text,
            "style": "yellow",
        }
    return None


def classify_dashboard_row(row: JsonDict) -> JsonDict:
    if row.get("error"):
        return {"key": "unavailable", "label": "不可用", "style": "red", "score": -1.0}
    remaining_7d = get_window_remaining_value(row, "7d")
    remaining_5h = get_window_remaining_value(row, "5h")
    effective_5h = get_effective_5h_remaining_percent(row)
    required_7d = get_required_7d_remaining_for_5h(remaining_5h)
    if remaining_7d is not None and remaining_7d <= 0.0:
        return {"key": "unavailable", "label": "不可用", "style": "red", "score": -1.0}
    status_key = "healthy"
    status_label = "良好"
    status_style = "green"
    if remaining_7d is not None and remaining_7d < SEVEN_DAY_PERCENT_PER_FULL_5H:
        status_key = "warning"
        status_label = "不足"
        status_style = "yellow"
    if remaining_5h is not None and remaining_5h <= 0.0:
        return {"key": "unavailable", "label": "不可用", "style": "red", "score": -1.0}
    if remaining_5h is not None and remaining_5h < 30.0 and status_key != "unavailable":
        status_key = "warning"
        status_label = "不足"
        status_style = "yellow"
    if (
        required_7d is not None
        and remaining_7d is not None
        and remaining_5h is not None
        and float(remaining_5h) > 0.0
        and float(remaining_7d) < float(required_7d)
    ):
        status_key = "warning"
        status_label = "不足"
        status_style = "yellow"
    score_candidates = [
        value for value in [remaining_7d, effective_5h] if value is not None
    ]
    score = min(score_candidates) if score_candidates else -1.0
    if status_key == "warning":
        score = min(score, 29.0)
    return {
        "key": status_key,
        "label": status_label,
        "style": status_style,
        "score": score,
    }


def summarize_dashboard_rows(rows: list[JsonDict]) -> dict[str, int]:
    summary = {"healthy": 0, "warning": 0, "unavailable": 0}
    for row in rows:
        status = classify_dashboard_row(row)
        summary[status["key"]] += 1
    return summary


def get_effective_remaining_percent(row: JsonDict) -> float | None:
    if row.get("error"):
        return None
    remaining_7d = get_window_remaining_value(row, "7d")
    effective_5h = get_effective_5h_remaining_percent(row)
    candidates = [value for value in (remaining_7d, effective_5h) if value is not None]
    if not candidates:
        return None
    return max(0.0, min(candidates))


def summarize_dashboard_capacity(rows: list[JsonDict]) -> JsonDict:
    values = [
        value
        for value in (get_effective_remaining_percent(row) for row in rows)
        if value is not None
    ]
    unknown = max(0, len(rows) - len(values))
    if not values:
        return {
            "counted": 0,
            "unknown": unknown,
            "remainingPercent": 0.0,
            "style": "red",
            "hint": "暂无可用汇总数据",
        }
    remaining_percent = sum(values) / len(values)
    style = quota_style_name(remaining_percent)
    hint = "整体还可用"
    if remaining_percent <= 15.0:
        hint = "整体快见底了"
    elif remaining_percent <= 45.0:
        hint = "整体开始偏紧"
    return {
        "counted": len(values),
        "unknown": unknown,
        "remainingPercent": remaining_percent,
        "style": style,
        "hint": hint,
    }


def filter_dashboard_rows(rows: list[JsonDict], filter_key: str) -> list[JsonDict]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -float(classify_dashboard_row(row)["score"]),
            str(row.get("displayName") or row.get("alias") or ""),
        ),
    )
    if filter_key == "available":
        return [
            row
            for row in ordered
            if classify_dashboard_row(row)["key"] != "unavailable"
        ]
    if filter_key == "unavailable":
        return [
            row
            for row in ordered
            if classify_dashboard_row(row)["key"] == "unavailable"
        ]
    return ordered


def pick_homepage_rows(rows: list[JsonDict], max_slots: int = 3) -> list[JsonDict]:
    if len(rows) <= max_slots:
        return rows
    current_row = next((row for row in rows if row.get("isCurrent")), None)
    remaining_rows = [row for row in rows if row is not current_row]
    remaining_rows.sort(
        key=lambda row: (
            -float(classify_dashboard_row(row)["score"]),
            str(row.get("displayName") or row.get("alias") or ""),
        )
    )
    picked: list[JsonDict] = []
    if current_row is not None:
        picked.append(current_row)
    for row in remaining_rows:
        if len(picked) >= max_slots:
            break
        picked.append(row)
    return picked


def format_compact_duration_ms(duration_ms: int) -> str:
    remaining_ms = max(0, int(duration_ms))
    total_seconds = remaining_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分钟"
    if minutes > 0:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def get_dashboard_next_refresh_at(state: DashboardState) -> int | None:
    if not state.monitoring_enabled or state.auto_refresh_interval_ms <= 0:
        return None
    if state.last_refresh_at_ms is None:
        return current_time_ms()
    return int(state.last_refresh_at_ms) + int(state.auto_refresh_interval_ms)


def should_auto_refresh_dashboard(
    state: DashboardState, now_ms: int | None = None
) -> bool:
    next_refresh_at = get_dashboard_next_refresh_at(state)
    if next_refresh_at is None:
        return False
    base_ms = now_ms if now_ms is not None else current_time_ms()
    return int(base_ms) >= int(next_refresh_at)


def build_dashboard_monitor_text(
    state: DashboardState, now_ms: int | None = None
) -> str:
    if not state.monitoring_enabled:
        return "[dim]监控已关闭[/dim]"
    frame = MONITOR_FRAMES[state.monitor_frame_index % len(MONITOR_FRAMES)]
    return f"[bold cyan]监控[/bold cyan] {frame}"


def build_dashboard_panel_subtitle(state: DashboardState) -> str | None:
    if state.monitoring_enabled:
        return build_dashboard_monitor_text(state)
    return None


def strip_rich_markup(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", text)


def escape_panel_text(value: str) -> str:
    return escape_rich_markup(value)


def get_terminal_display_width(text: str) -> int:
    width = 0
    for char in text:
        if char in {"\n", "\r"}:
            continue
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def align_panel_columns(
    left_markup: str, right_markup: str | None = None, width_hint: int = 72
) -> str:
    plain_left = strip_rich_markup(left_markup)
    if not right_markup:
        padding = max(0, width_hint - get_terminal_display_width(plain_left))
        return f"{left_markup}{' ' * padding}"
    plain_right = strip_rich_markup(right_markup)
    gap = max(
        2,
        width_hint
        - get_terminal_display_width(plain_left)
        - get_terminal_display_width(plain_right),
    )
    return f"{left_markup}{' ' * gap}{right_markup}"


def build_panel_title(status_markup: str | None = None, width_hint: int = 72) -> Text:
    base = APP_NAME
    if not status_markup:
        return Text(base)
    plain_status = strip_rich_markup(status_markup)
    base_width = get_terminal_display_width(base)
    status_width = get_terminal_display_width(plain_status)
    centered_start = max(0, (width_hint - base_width) // 2)
    right_padding = max(2, width_hint - centered_start - base_width - status_width)
    return Text.from_markup(
        f"{' ' * centered_start}{base}{' ' * right_padding}{status_markup}"
    )


def build_dashboard_panel_footer_status(state: DashboardState) -> str | None:
    if not state.is_refreshing:
        return None
    frame = REFRESH_BAR_FRAMES[state.refresh_frame_index % len(REFRESH_BAR_FRAMES)]
    return f"[cyan]{frame} {state.refresh_message}[/cyan]"


def build_panel_header_line(
    status_markup: str | None = None, width_hint: int = 72
) -> str:
    title = f"{APP_NAME} v{APP_RELEASE_VERSION}"
    title_markup = (
        f"[bold cyan]{APP_NAME}[/bold cyan] [dim]v{APP_RELEASE_VERSION}[/dim]"
    )
    title_width = get_terminal_display_width(title)
    title_start = max(0, (width_hint - title_width) // 2)
    if not status_markup:
        return f"{' ' * title_start}{title_markup}"
    status_plain = strip_rich_markup(status_markup)
    status_width = get_terminal_display_width(status_plain)
    right_gap = max(2, width_hint - title_start - title_width - status_width)
    return f"{' ' * title_start}{title_markup}{' ' * right_gap}{status_markup}"


def build_panel_footer_line(
    status_markup: str | None = None, width_hint: int = 72
) -> str | None:
    if not status_markup:
        return None
    return f" {status_markup}"


def build_section_header_line(
    left_label: str, right_status: str | None = None, width_hint: int = 72
) -> str:
    left_markup = f"[bold cyan]{left_label}[/bold cyan]"
    if not right_status:
        return left_markup
    right_plain = strip_rich_markup(right_status)
    gap = max(
        2,
        width_hint
        - get_terminal_display_width(left_label)
        - get_terminal_display_width(right_plain),
    )
    return f"{left_markup}{' ' * gap}{right_status}"


def compose_panel_body(
    content: str, title_status: str | None = None, footer_status: str | None = None
) -> str:
    lines = [
        build_panel_header_line(title_status, width_hint=PANEL_CONTENT_WIDTH),
        content,
    ]
    footer_line = build_panel_footer_line(footer_status, width_hint=PANEL_CONTENT_WIDTH)
    if footer_line:
        lines.extend(["", footer_line])
    return "\n".join(lines)


def show_live_panel(panel: Panel, key_reader: Callable[[], str] | None = None) -> str:
    with Live(panel, console=console, screen=True, auto_refresh=False) as live:
        live.update(panel, refresh=True)
        reader = key_reader or read_key
        return reader()


def set_default_console_size(
    cols: int = DEFAULT_WINDOW_COLS, lines: int = DEFAULT_WINDOW_LINES
) -> None:
    if os.name != "nt":
        return
    safe_cols = max(PANEL_WIDTH + 2, int(cols))
    safe_lines = max(30, int(lines))
    try:
        sys.stdout.write(f"\x1b[8;{safe_lines};{safe_cols}t")
        sys.stdout.flush()
    except Exception:
        pass
    try:
        os.system(f"mode con: cols={safe_cols} lines={safe_lines} >nul 2>nul")
    except Exception:
        pass


def build_loading_panel(
    content: str, header_status: str | None, footer_status: str | None
) -> Panel:
    return Panel(
        compose_panel_body(
            content, title_status=header_status, footer_status=footer_status
        ),
        border_style="cyan",
        padding=(0, 1),
        width=PANEL_WIDTH,
    )


def format_step_log_lines(lines: list[str]) -> str:
    if not lines:
        return "[dim]正在准备初始化步骤...[/dim]"
    return "\n".join(lines)


class StepLogStatus:
    def __init__(
        self, message: str, delay_seconds: float = STEP_LOG_DELAY_SECONDS
    ) -> None:
        self.lines: list[str] = [f"[bold cyan][1/1][/bold cyan] {message}"]
        self.delay_seconds = max(0.0, delay_seconds)
        self.live: Live | None = None
        self._last_update_at = 0.0

    def __enter__(self) -> "StepLogStatus":
        panel = build_loading_panel(
            format_step_log_lines(self.lines),
            header_status="初始化",
            footer_status=None,
        )
        self.live = Live(panel, console=console, screen=True, auto_refresh=False)
        self.live.__enter__()
        self.live.update(panel, refresh=True)
        self._last_update_at = time.monotonic()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.live is not None:
            self.live.__exit__(exc_type, exc, tb)
            self.live = None

    def update(self, message: str) -> None:
        self.lines.append(f"[green][OK][/green] {message}")
        if self.live is not None:
            panel = build_loading_panel(
                format_step_log_lines(self.lines),
                header_status="初始化",
                footer_status=None,
            )
            self.live.update(panel, refresh=True)
        now = time.monotonic()
        elapsed = now - self._last_update_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        self._last_update_at = time.monotonic()

    def complete_success(self, title: str, detail: str | None = None) -> None:
        self.lines.extend(
            [
                "",
                f"[bold green]{title}[/bold green]",
            ]
        )
        if detail:
            self.lines.append(detail)
        self.lines.append("现在可以点击继续了")
        if self.live is not None:
            panel = build_loading_panel(
                format_step_log_lines(self.lines),
                header_status="初始化",
                footer_status=None,
            )
            self.live.update(panel, refresh=True)
        read_key()


def build_menu_screen(
    panel_text: str,
    options: list[JsonDict],
    index: int,
    hint: str = "",
    panel_header_status: str | None = None,
    panel_footer_status: str | None = None,
) -> Group:
    menu_panel = build_menu_panel(options, index)
    blocks: list[Any] = [
        Panel.fit(
            compose_panel_body(
                panel_text, title_status=panel_header_status, footer_status=None
            ),
            border_style="cyan",
            padding=(0, 1),
        ),
        menu_panel,
    ]
    footer_line = build_panel_footer_line(panel_footer_status)
    if footer_line:
        blocks.append(footer_line)
    if hint:
        blocks.append(f"[dim]{hint}[/dim]")
    return Group(*blocks)


def render_home_dashboard_text(
    rows: list[JsonDict],
    current_alias: str,
    max_slots: int = 3,
) -> str:
    picked_rows = pick_homepage_rows(rows, max_slots=max_slots)
    summary = summarize_dashboard_rows(rows)
    capacity = summarize_dashboard_capacity(rows)
    header_divider = f"[dim]{'═' * 72}[/dim]"
    capacity_bar = colorize_progress_bar(
        progress_bar(100.0 - float(capacity["remainingPercent"]), width=32),
        str(capacity["style"]),
    )
    summary_line = (
        f"[green]良好 {summary['healthy']}[/green]"
        f" [dim]·[/dim] [yellow]不足 {summary['warning']}[/yellow]"
        f" [dim]·[/dim] [red]不可用 {summary['unavailable']}[/red]"
    )
    lines = [
        f"[bold cyan]{HOME_PANEL_TITLE}[/bold cyan]",
        header_divider,
        summary_line,
        (
            f"[dim]整体平均可用[/dim] {capacity_bar} "
            f"[{capacity['style']}]{float(capacity['remainingPercent']):.1f}%[/{capacity['style']}]"
        ),
        header_divider,
        "",
    ]
    lines.append(
        render_dashboard_text(picked_rows, current_alias, include_header=False)
    )
    return "\n".join(lines)


def build_status_preview_rows() -> list[JsonDict]:
    return [
        {
            "alias": "current-ok",
            "displayName": "当前账号",
            "accountId": "acct-current",
            "isCurrent": True,
            "plan": "team",
            "groups": [],
            "windows": [
                {
                    "label": "5h",
                    "usedPercent": 12.0,
                    "resetAt": current_time_ms() + 5 * 3600 * 1000,
                },
                {
                    "label": "7d",
                    "usedPercent": 28.0,
                    "resetAt": current_time_ms() + 7 * 86400 * 1000,
                },
            ],
            "error": None,
        },
        {
            "alias": "tight",
            "displayName": "额度偏紧",
            "accountId": "acct-tight",
            "isCurrent": False,
            "plan": "team",
            "groups": [],
            "windows": [
                {
                    "label": "5h",
                    "usedPercent": 78.0,
                    "resetAt": current_time_ms() + 2 * 3600 * 1000,
                },
                {
                    "label": "7d",
                    "usedPercent": 74.0,
                    "resetAt": current_time_ms() + 4 * 86400 * 1000,
                },
            ],
            "error": None,
        },
        {
            "alias": "empty",
            "displayName": "额度耗尽",
            "accountId": "acct-empty",
            "isCurrent": False,
            "plan": "team",
            "groups": [],
            "windows": [
                {
                    "label": "5h",
                    "usedPercent": 100.0,
                    "resetAt": current_time_ms() + 30 * 60 * 1000,
                },
                {
                    "label": "7d",
                    "usedPercent": 100.0,
                    "resetAt": current_time_ms() + 86400 * 1000,
                },
            ],
            "error": None,
        },
        {
            "alias": "expired",
            "displayName": "过期账号",
            "accountId": "acct-expired",
            "isCurrent": False,
            "plan": "未知",
            "groups": [],
            "windows": [],
            "error": "登录态已失效（401），请重新登录后再试",
        },
        {
            "alias": "workspace-bad",
            "displayName": "工作组异常",
            "accountId": "acct-workspace",
            "isCurrent": False,
            "plan": "未知",
            "groups": [],
            "windows": [],
            "error": "接口拒绝访问（403），工作组信息可能暂时不可读",
        },
    ]


def build_status_screen(message: str, detail: str | None = None) -> str:
    lines = [message]
    if detail:
        lines.extend(["", detail])
    lines.extend(["", "按任意键返回"])
    return "\n".join(lines)


def read_key() -> str:
    if os.name == "nt":
        import msvcrt

        first = msvcrt.getwch()
        if first in ("\x00", "\xe0"):
            second = msvcrt.getwch()
            if second == "H":
                return "up"
            if second == "P":
                return "down"
            if second == "K":
                return "left"
            if second == "M":
                return "right"
            return "unknown"
        if first == "\r":
            return "enter"
        if first == "\x1b":
            return "escape"
        if first == "\x08":
            return "backspace"
        return first
    if not sys.stdin.isatty():
        return "enter"
    with raw_stdin_mode():
        first = sys.stdin.read(1)
        if first == "\x1b":
            ready, _, _ = select.select([sys.stdin], [], [], 0.03)
            if not ready:
                return "escape"
            second = sys.stdin.read(1)
            if second == "[":
                third = sys.stdin.read(1)
                if third == "A":
                    return "up"
                if third == "B":
                    return "down"
                if third == "C":
                    return "right"
                if third == "D":
                    return "left"
                return "unknown"
            return "escape"
        if first in {"\r", "\n"}:
            return "enter"
        if first in {"\x7f", "\b"}:
            return "backspace"
        return first


def read_key_with_timeout(timeout_ms: int | None = None) -> str | None:
    if timeout_ms is None:
        return read_key()
    if os.name != "nt":
        if not sys.stdin.isatty():
            time.sleep(max(0.0, float(timeout_ms) / 1000.0))
            return None
        timeout_seconds = max(0.0, float(timeout_ms) / 1000.0)
        with raw_stdin_mode():
            ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
            if not ready:
                return None
            first = sys.stdin.read(1)
            if first == "\x1b":
                ready, _, _ = select.select([sys.stdin], [], [], 0.03)
                if not ready:
                    return "escape"
                second = sys.stdin.read(1)
                if second == "[":
                    third = sys.stdin.read(1)
                    if third == "A":
                        return "up"
                    if third == "B":
                        return "down"
                    if third == "C":
                        return "right"
                    if third == "D":
                        return "left"
                    return "unknown"
                return "escape"
            if first in {"\r", "\n"}:
                return "enter"
            if first in {"\x7f", "\b"}:
                return "backspace"
            return first
    import msvcrt

    deadline = time.monotonic() + max(0.0, float(timeout_ms) / 1000.0)
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            return read_key()
        time.sleep(0.05)
    if msvcrt.kbhit():
        return read_key()
    return None


def choose_from_menu(
    title: str | Callable[[], str],
    options: list[JsonDict],
    hint: str = "",
    idle_timeout_ms: int | None = None,
    idle_action: Callable[[], bool] | None = None,
    panel_header_status: str | Callable[[], str | None] | None = None,
    panel_footer_status: str | Callable[[], str | None] | None = None,
) -> JsonDict | None:
    if not options:
        return None
    index = 0

    def render_current() -> Group:
        panel_text = title() if callable(title) else title
        header_status_text = (
            panel_header_status()
            if callable(panel_header_status)
            else panel_header_status
        )
        footer_status_text = (
            panel_footer_status()
            if callable(panel_footer_status)
            else panel_footer_status
        )
        return build_menu_screen(
            panel_text,
            options,
            index,
            hint=hint,
            panel_header_status=header_status_text,
            panel_footer_status=footer_status_text,
        )

    with Live(
        render_current(), console=console, screen=True, auto_refresh=False
    ) as live:
        while True:
            key = read_key_with_timeout(idle_timeout_ms)
            if key is None:
                should_rerender = False
                if idle_action is not None:
                    should_rerender = idle_action()
                if should_rerender:
                    live.update(render_current(), refresh=True)
                continue
            if key == "up":
                index = (index - 1) % len(options)
                live.update(render_current(), refresh=True)
            elif key == "down":
                index = (index + 1) % len(options)
                live.update(render_current(), refresh=True)
            elif key == "enter":
                return options[index]
            elif key in {"escape", "left"}:
                return None


def build_menu_panel(options: list[JsonDict], index: int) -> Group:
    rows: list[str] = []
    content_width = PANEL_WIDTH - 4
    for i, option in enumerate(options):
        selected_prefix = str(option.get("selectedPrefix", "▶" if i == index else " "))
        fixed_prefix = str(option.get("prefix", "") or "")
        label = escape_panel_text(str(option.get("label", "")))
        description = escape_panel_text(
            str(option.get("description", "") or "").strip()
        )
        meta = escape_panel_text(str(option.get("meta", "") or "").strip())
        badge = str(option.get("badge", "") or "").strip()
        prefix_block = f"{selected_prefix} {fixed_prefix} "
        line = align_panel_columns(
            f" {prefix_block}{label}", badge or None, content_width
        )
        if i == index:
            content = f"[bold #07131f on #7fdcff]{line}[/]"
        else:
            content = f"[#eef6ff on #08101c]{line}[/]"
        rows.append(content)
        if description:
            desc_line = align_panel_columns(
                f"   {description}", meta or None, content_width
            )
            if i == index:
                rows.append(f"[#0d2233 on #d9f5ff]{desc_line}[/]")
            else:
                rows.append(f"[#7f8ea3 on #08101c]{desc_line}[/]")
    return Group(*rows)


def build_account_choice_options(
    accounts: dict[str, JsonDict], current_alias: str | None = None
) -> list[JsonDict]:
    options: list[JsonDict] = []

    def sort_key(item: tuple[str, JsonDict]) -> tuple[int, str, str]:
        alias, profile = item
        display_name = get_account_display_name(alias, profile)
        return (0 if alias == current_alias else 1, display_name.lower(), alias.lower())

    for alias, profile in sorted(accounts.items(), key=sort_key):
        if not isinstance(alias, str) or not isinstance(profile, dict):
            continue
        display_name = get_account_display_name(alias, profile)
        is_current = alias == current_alias
        options.append(
            {
                "key": alias,
                "label": display_name,
                "prefix": "▶" if is_current else " ",
                "selectedPrefix": " ",
                "description": "",
                "meta": "",
                "badge": "",
            }
        )
    return options


def build_account_picker_text(title: str, hint: str, account_count: int) -> str:
    divider = f"[dim]{'─' * PANEL_CONTENT_WIDTH}[/dim]"
    summary = f"[dim]共 {account_count} 个账号[/dim]"
    return "\n".join(
        [
            build_section_header_line(title, summary, width_hint=PANEL_CONTENT_WIDTH),
            divider,
            f"[#cfe7ff]{hint}[/#cfe7ff]",
            "[dim]↑↓ 选择 · Enter 确认 · Esc 返回[/dim]",
        ]
    )


def prompt_text(prompt: str) -> str | None:
    console.print(f"[bold cyan]{prompt}[/bold cyan]")
    console.print("[dim]输入内容后回车；直接回车表示取消[/dim]")
    show_cursor()
    try:
        console.print("[bold cyan]>[/bold cyan] ", end="")
        value = input().strip()
    finally:
        hide_cursor()
    return value or None


def pause_message(message: str) -> None:
    _ = show_live_panel(
        Panel.fit(build_status_screen(message), border_style="green", title=APP_NAME)
    )


def show_status_screen(message: str, detail: str | None = None) -> None:
    _ = show_live_panel(
        Panel.fit(
            build_status_screen(message, detail), border_style="green", title=APP_NAME
        )
    )


def switch_audit_log_file(root: Path = ROOT) -> Path:
    return root / "logs" / "switch-events.jsonl"


def write_switch_audit_event(event: JsonDict, root: Path = ROOT) -> None:
    payload = {"timestamp": now_iso(), **event}
    try:
        append_jsonl(switch_audit_log_file(root), payload)
    except Exception as exc:
        print(f"[audit-log] 写入切号日志失败：{exc}", file=sys.stderr)


def format_switch_audit_entry(entry: JsonDict) -> str:
    timestamp = str(entry.get("timestamp") or "未知时间")
    mode = str(entry.get("mode") or "unknown")
    status = str(entry.get("status") or "unknown")
    from_alias = str(entry.get("fromAlias") or "未知")
    to_alias = str(entry.get("toAlias") or "未知")
    reason = str(entry.get("reasonCode") or entry.get("reason") or "未记录原因")
    error = str(entry.get("error") or "").strip()
    detail = f"[{timestamp}] {mode}/{status} {from_alias} -> {to_alias} | {reason}"
    if error:
        return f"{detail} | error={error}"
    return detail


def cmd_logs(limit: int = 20, root: Path = ROOT) -> int:
    log_path = switch_audit_log_file(root)
    if not log_path.exists():
        print("还没有切号日志。")
        print(f"- 日志路径：{log_path}")
        return 0
    entries: list[JsonDict] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
    if not entries:
        print("切号日志文件存在，但里面没有有效记录。")
        print(f"- 日志路径：{log_path}")
        return 0
    print(f"切号日志（最近 {min(limit, len(entries))} 条）：")
    print(f"- 日志路径：{log_path}")
    for entry in entries[-max(1, int(limit)) :]:
        print(format_switch_audit_entry(entry))
    return 0


def run_with_loading(
    message: str,
    action: Callable[..., Any],
    status_factory: Callable[[str], Any] | None = None,
    on_success: Callable[[Any, Any], None] | None = None,
) -> Any:
    factory = status_factory or (lambda status_message: StepLogStatus(status_message))
    clear_screen()
    with factory(message) as status:

        def progress(step_message: str) -> None:
            if hasattr(status, "update"):
                status.update(step_message)

        parameter_count = len(inspect.signature(action).parameters)
        if parameter_count >= 1:
            result = action(progress)
        else:
            result = action()
        if on_success is not None:
            on_success(status, result)
        return result


def run_action_with_status(
    action: Callable[[], int | str | None], success_message: str
) -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = action()
    detail = buffer.getvalue().strip()
    if isinstance(result, str) and result.strip():
        detail = (detail + "\n" + result).strip() if detail else result.strip()
    show_status_screen(success_message, detail or None)


def root_agents_dir(root: Path) -> Path:
    return root / "agents"


def root_store_file(root: Path) -> Path:
    return root / "openai-codex-accounts.json"


def root_openclaw_config_file(root: Path) -> Path:
    return root / "openclaw.json"


def login_session_file(root: Path = ROOT) -> Path:
    return root / "openai-codex-login-session.json"


def agent_dirs(root: Path = ROOT) -> list[Path]:
    agents_root = root_agents_dir(root)
    if not agents_root.exists():
        return []
    out: list[Path] = []
    for item in agents_root.iterdir():
        p = item / "agent"
        if p.is_dir():
            out.append(p)
    return out


def extract_current_profile(root: Path = ROOT) -> JsonDict:
    for adir in agent_dirs(root):
        ap = read_json(adir / "auth-profiles.json")
        profile = ap.get("profiles", {}).get(PROFILE_KEY)
        if (
            isinstance(profile, dict)
            and profile.get("type") == "oauth"
            and profile.get("refresh")
        ):
            return {
                "type": "oauth",
                "provider": PROVIDER_KEY,
                "access": profile.get("access", ""),
                "refresh": profile.get("refresh", ""),
                "expires": profile.get("expires", 0),
                "accountId": profile.get("accountId", ""),
            }

    for adir in agent_dirs(root):
        auth = read_json(adir / "auth.json")
        profile = auth.get(PROVIDER_KEY)
        if (
            isinstance(profile, dict)
            and profile.get("type") == "oauth"
            and profile.get("refresh")
        ):
            return {
                "type": "oauth",
                "provider": PROVIDER_KEY,
                "access": profile.get("access", ""),
                "refresh": profile.get("refresh", ""),
                "expires": profile.get("expires", 0),
                "accountId": profile.get("accountId", ""),
            }

    raise ValueError(
        "No current openai-codex oauth token found under ~/.openclaw/agents/*/agent"
    )


def load_store(root: Path = ROOT) -> JsonDict:
    data = read_json(root_store_file(root))
    if not data:
        data = {"version": 1, "active": None, "accounts": {}, "updatedAt": now_iso()}
    if "accounts" not in data or not isinstance(data["accounts"], dict):
        data["accounts"] = {}
    return data


def save_store(data: JsonDict, root: Path = ROOT) -> None:
    data["updatedAt"] = now_iso()
    write_json(root_store_file(root), data)


def ensure_store_file(root: Path = ROOT) -> JsonDict:
    data = load_store(root)
    save_store(data, root)
    return data


def detect_openclaw_agent_model_files(root: Path = ROOT) -> list[Path]:
    return [adir / "models.json" for adir in agent_dirs(root)]


def ensure_openclaw_model_aliases(config: JsonDict) -> bool:
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    model_aliases = defaults.setdefault("models", {})
    key = f"{PROVIDER_KEY}/{TARGET_OPENCLAW_MODEL_ID}"
    if isinstance(model_aliases.get(key), dict):
        return False
    model_aliases[key] = {"alias": TARGET_OPENCLAW_MODEL_ALIAS}
    return True


def ensure_openclaw_workspace_defaults(config: JsonDict, root: Path) -> bool:
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    target_workspace = str(root / "workspace")
    if str(defaults.get("workspace") or "") == target_workspace:
        return False
    defaults["workspace"] = target_workspace
    return True


def ensure_openclaw_auth_profile_defaults(config: JsonDict) -> bool:
    auth = config.setdefault("auth", {})
    profiles = auth.setdefault("profiles", {})
    if isinstance(profiles.get(PROFILE_KEY), dict):
        return False
    profiles[PROFILE_KEY] = {"provider": PROVIDER_KEY, "mode": "oauth"}
    return True


def load_app_state(root: Path = ROOT) -> JsonDict:
    data = read_json(APP_STATE_FILE if root == ROOT else root / APP_STATE_FILE.name)
    if not isinstance(data, dict):
        data = {}
    return data


def save_app_state(data: JsonDict, root: Path = ROOT) -> None:
    target = APP_STATE_FILE if root == ROOT else root / APP_STATE_FILE.name
    write_json(target, data)


def load_dashboard_snapshot_rows(root: Path = ROOT) -> list[JsonDict]:
    state = load_app_state(root)
    snapshot = state.get("dashboardSnapshot")
    if not isinstance(snapshot, dict):
        return []
    rows_by_alias = snapshot.get("rowsByAlias")
    if not isinstance(rows_by_alias, dict):
        return []
    rows = [
        row
        for row in rows_by_alias.values()
        if isinstance(row, dict) and row.get("alias")
    ]
    rows.sort(
        key=lambda item: (not bool(item.get("isCurrent")), str(item.get("alias") or ""))
    )
    return rows


def save_dashboard_snapshot_rows(rows: list[JsonDict], root: Path = ROOT) -> None:
    state = load_app_state(root)
    snapshot = state.get("dashboardSnapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    rows_by_alias: dict[str, JsonDict] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("alias"):
            continue
        rows_by_alias[str(row.get("alias") or "")] = deep_copy_json(row)
    snapshot["rowsByAlias"] = rows_by_alias
    snapshot["updatedAt"] = now_iso()
    state["dashboardSnapshot"] = snapshot
    save_app_state(state, root)


def ensure_app_state_touch(root: Path = ROOT) -> None:
    state = load_app_state(root)
    state["lastTouchedVersion"] = INIT_VERSION
    state["lastTouchedAt"] = now_iso()
    save_app_state(state, root)


def set_init_status(root: Path, completed: bool, verified: bool) -> None:
    state = load_app_state(root)
    state["initCompleted"] = completed
    state["initVerified"] = verified
    state["initVersion"] = INIT_VERSION
    state["lastTouchedVersion"] = INIT_VERSION
    state["lastTouchedAt"] = now_iso()
    if completed and "initializedAt" not in state:
        state["initializedAt"] = now_iso()
    elif completed:
        state["initializedAt"] = now_iso()
    save_app_state(state, root)


def cleanup_openclaw_meta(config: JsonDict, root: Path = ROOT) -> bool:
    meta = config.get("meta")
    if not isinstance(meta, dict):
        return False
    keys_to_move = [
        "lastTouchedVersion",
        "lastTouchedAt",
        "initCompleted",
        "initVerified",
        "initVersion",
        "initializedAt",
    ]
    state = load_app_state(root)
    changed = False
    for key in keys_to_move:
        if key in meta:
            state[key] = meta.pop(key)
            changed = True
    if changed:
        save_app_state(state, root)
    if isinstance(meta, dict) and not meta:
        config.pop("meta", None)
        changed = True
    return changed


def ensure_default_agent_dirs(root: Path = ROOT) -> list[Path]:
    agents_root = root_agents_dir(root)
    created: list[Path] = []
    default_aliases = ["main", "product", "ad-ops"]
    for alias in default_aliases:
        agent_root = agents_root / alias / "agent"
        agent_root.mkdir(parents=True, exist_ok=True)
        auth_path = agent_root / "auth.json"
        auth_profiles_path = agent_root / "auth-profiles.json"
        models_path = agent_root / "models.json"
        if not auth_path.exists():
            write_json(auth_path, {})
        if not auth_profiles_path.exists():
            write_json(
                auth_profiles_path,
                {"version": 1, "profiles": {}, "lastGood": {}, "usageStats": {}},
            )
        if not models_path.exists():
            write_json(models_path, {})
        created.append(agent_root)
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    return created


def build_init_failure_detail(reason: str, target_path: Path | None = None) -> str:
    path_text = f"\n检测路径：{target_path}" if target_path is not None else ""
    if reason == "openclaw-config-missing":
        return f"找不到 OpenClAW 配置文件。{path_text}\n建议目录：{root_openclaw_config_file(ROOT)}\n请先确认 OpenClAW 已安装或目录已准备好，然后重新启动程序。"
    if reason == "openclaw-model-missing":
        return f"OpenClAW 配置里缺少 {TARGET_OPENCLAW_MODEL_ID}。{path_text}\n请重新运行初始化；如果仍失败，检查配置文件是否只读。"
    if reason == "openclaw-agents-missing":
        return f"找不到 OpenClAW agent 目录。{path_text}\n建议目录：{root_agents_dir(ROOT)}\n请先确认 OpenClAW 已正确初始化 agent 目录，然后重新启动程序。"
    if reason == "openclaw-agent-model-missing":
        return f"OpenClAW agent 模型文件里缺少 {TARGET_OPENCLAW_MODEL_ID}。{path_text}\n请重新运行初始化；如果仍失败，检查该文件写入权限。"
    if reason == "opencode-config-missing":
        return f"找不到 OpenCode 配置文件。{path_text}\n建议目录：{OPENCODE_CONFIG_FILE}\n请先确认 OpenCode 已安装或目录已准备好，然后重新启动程序。"
    if reason == "opencode-model-missing":
        return f"OpenCode 配置里缺少 {TARGET_OPENCODE_MODEL_KEY}。{path_text}\n请重新运行初始化；如果仍失败，检查配置文件是否只读。"
    if reason == "opencode-auth-missing":
        return f"找不到 OpenCode 凭据文件。{path_text}\n建议目录：{OPENCODE_AUTH_FILE}\n请确认 OpenCode 状态目录存在，然后重新启动程序。"
    if reason == "init-marker-missing":
        return f"环境文件存在，但初始化标记未写入。{path_text}\n程序会自动重新初始化；如果反复出现，请检查配置文件写入权限。"
    return f"初始化验证失败。{path_text}\n请检查 OpenClAW / OpenCode 目录是否可写，然后重新启动程序。"


def verify_initialized_environment(
    root: Path = ROOT,
    openclaw_config_path: Path | None = None,
    opencode_config_path: Path = OPENCODE_CONFIG_FILE,
    opencode_auth_path: Path = OPENCODE_AUTH_FILE,
    require_marker: bool = True,
) -> JsonDict:
    resolved_openclaw_config_path = openclaw_config_path or root_openclaw_config_file(
        root
    )
    model_files: list[Path] = []
    if variant_requires_openclaw_login():
        openclaw_config = read_json(resolved_openclaw_config_path)
        if not resolved_openclaw_config_path.exists():
            return {
                "ok": False,
                "reason": "openclaw-config-missing",
                "detail": build_init_failure_detail(
                    "openclaw-config-missing", resolved_openclaw_config_path
                ),
            }

        model_files = detect_openclaw_agent_model_files(root)
        if not model_files:
            return {
                "ok": False,
                "reason": "openclaw-agents-missing",
                "detail": build_init_failure_detail(
                    "openclaw-agents-missing", root_agents_dir(root)
                ),
            }

        provider_models = (
            openclaw_config.get("models", {})
            .get("providers", {})
            .get(PROVIDER_KEY, {})
            .get("models", [])
        )
        if not any(
            str(item.get("id") or "") == TARGET_OPENCLAW_MODEL_ID
            for item in provider_models
            if isinstance(item, dict)
        ):
            return {
                "ok": False,
                "reason": "openclaw-model-missing",
                "detail": build_init_failure_detail(
                    "openclaw-model-missing", resolved_openclaw_config_path
                ),
            }

        for models_path in model_files:
            model_config = read_json(models_path)
            agent_models = (
                model_config.get("providers", {})
                .get(PROVIDER_KEY, {})
                .get("models", [])
            )
            if not any(
                str(item.get("id") or "") == TARGET_OPENCLAW_MODEL_ID
                for item in agent_models
                if isinstance(item, dict)
            ):
                return {
                    "ok": False,
                    "reason": "openclaw-agent-model-missing",
                    "detail": build_init_failure_detail(
                        "openclaw-agent-model-missing", models_path
                    ),
                }

    if variant_requires_opencode_config():
        opencode_config = read_json(opencode_config_path)
        if not opencode_config_path.exists():
            return {
                "ok": False,
                "reason": "opencode-config-missing",
                "detail": build_init_failure_detail(
                    "opencode-config-missing", opencode_config_path
                ),
            }
        opencode_models = (
            opencode_config.get("provider", {}).get("openai", {}).get("models", {})
        )
        if not isinstance(opencode_models.get(TARGET_OPENCODE_MODEL_KEY), dict):
            return {
                "ok": False,
                "reason": "opencode-model-missing",
                "detail": build_init_failure_detail(
                    "opencode-model-missing", opencode_config_path
                ),
            }

        if not opencode_auth_path.exists():
            return {
                "ok": False,
                "reason": "opencode-auth-missing",
                "detail": build_init_failure_detail(
                    "opencode-auth-missing", opencode_auth_path
                ),
            }

    app_state = load_app_state(root)
    if require_marker and not (
        app_state.get("initCompleted")
        and app_state.get("initVerified")
        and app_state.get("initVersion") == INIT_VERSION
    ):
        return {
            "ok": False,
            "reason": "init-marker-missing",
            "detail": build_init_failure_detail(
                "init-marker-missing", resolved_openclaw_config_path
            ),
        }

    return {
        "ok": True,
        "reason": None,
        "detail": "初始化已完成并验证通过",
        "openclaw_config_path": resolved_openclaw_config_path,
        "opencode_config_path": opencode_config_path,
        "opencode_auth_path": opencode_auth_path,
        "agent_model_files": model_files,
    }


def ensure_openclaw_provider_model(config: JsonDict) -> bool:
    models = config.setdefault("models", {})
    models.setdefault("mode", "merge")
    providers = models.setdefault("providers", {})
    provider = providers.setdefault(
        PROVIDER_KEY,
        {
            "baseUrl": "https://api.openai.com",
            "api": "openai-completions",
            "models": [],
        },
    )
    provider.setdefault("baseUrl", "https://api.openai.com")
    provider.setdefault("api", "openai-completions")
    model_list = provider.setdefault("models", [])
    template = next(
        (
            item
            for item in model_list
            if isinstance(item, dict)
            and str(item.get("id") or "") in {"gpt-5.3-codex", TARGET_OPENCLAW_MODEL_ID}
        ),
        next(
            (
                item
                for item in model_list
                if isinstance(item, dict)
                and str(item.get("id") or "").startswith("gpt-5.")
            ),
            None,
        ),
    )
    return ensure_model_entry(
        model_list,
        TARGET_OPENCLAW_MODEL_ID,
        lambda: clone_openclaw_model_entry(template),
    )


def ensure_openclaw_config(root: Path = ROOT, config_path: Path | None = None) -> Path:
    target_path = config_path or root_openclaw_config_file(root)
    config = read_json(target_path)
    changed = False
    changed = cleanup_openclaw_meta(config, root) or changed
    changed = ensure_openclaw_auth_profile_defaults(config) or changed
    changed = ensure_openclaw_provider_model(config) or changed
    changed = ensure_openclaw_model_aliases(config) or changed
    changed = ensure_openclaw_workspace_defaults(config, root) or changed
    if changed or not target_path.exists():
        write_json_with_backup(target_path, config)
    ensure_app_state_touch(root)
    return target_path


def ensure_agent_models_file(models_path: Path) -> Path:
    config = read_json(models_path)
    providers = config.setdefault("providers", {})
    provider = providers.setdefault(
        PROVIDER_KEY,
        {
            "baseUrl": "https://api.openai.com",
            "api": "openai-completions",
            "models": [],
        },
    )
    provider.setdefault("baseUrl", "https://api.openai.com")
    provider.setdefault("api", "openai-completions")
    model_list = provider.setdefault("models", [])
    template = next(
        (
            item
            for item in model_list
            if isinstance(item, dict)
            and str(item.get("id") or "") in {"gpt-5.3-codex", TARGET_OPENCLAW_MODEL_ID}
        ),
        next(
            (
                item
                for item in model_list
                if isinstance(item, dict)
                and str(item.get("id") or "").startswith("gpt-5.")
            ),
            None,
        ),
    )
    changed = ensure_model_entry(
        model_list,
        TARGET_OPENCLAW_MODEL_ID,
        lambda: clone_openclaw_model_entry(template),
    )
    if changed or not models_path.exists():
        write_json_with_backup(models_path, config)
    return models_path


def ensure_opencode_config(config_path: Path = OPENCODE_CONFIG_FILE) -> Path:
    config = read_json(config_path)
    if "$schema" not in config:
        config["$schema"] = "https://opencode.ai/config.json"
    providers = config.setdefault("provider", {})
    provider = providers.setdefault("openai", {"name": "OpenAI", "models": {}})
    provider.setdefault("name", "OpenAI")
    models = provider.setdefault("models", {})
    template = next(
        (
            value
            for key, value in models.items()
            if key in {"gpt-5.2", TARGET_OPENCODE_MODEL_KEY} and isinstance(value, dict)
        ),
        next(
            (
                value
                for key, value in models.items()
                if key.startswith("gpt-5") and isinstance(value, dict)
            ),
            None,
        ),
    )
    changed = ensure_named_model_entry(
        models, TARGET_OPENCODE_MODEL_KEY, lambda: clone_opencode_model_entry(template)
    )
    if changed or not config_path.exists():
        write_json_with_backup(config_path, config)
    return config_path


def ensure_opencode_auth_file(auth_path: Path = OPENCODE_AUTH_FILE) -> Path:
    auth_data = read_json(auth_path)
    if auth_path.exists():
        return auth_path
    write_json(auth_path, auth_data)
    return auth_path


def initialize_environment(
    root: Path = ROOT,
    openclaw_config_path: Path | None = None,
    opencode_config_path: Path = OPENCODE_CONFIG_FILE,
    opencode_auth_path: Path = OPENCODE_AUTH_FILE,
    progress_callback: Callable[[str], None] | None = None,
) -> JsonDict:
    root.mkdir(parents=True, exist_ok=True)
    resolved_openclaw_config_path = openclaw_config_path or root_openclaw_config_file(
        root
    )
    agent_model_files: list[Path] = []
    if variant_requires_openclaw_login():
        if progress_callback is not None:
            progress_callback("步骤 1/5 检查 OpenClAW 目录")
        ensure_store_file(root)
        ensure_default_agent_dirs(root)
        if progress_callback is not None:
            progress_callback("步骤 2/5 检查 OpenClAW 配置")
        resolved_openclaw_config_path = ensure_openclaw_config(
            root, openclaw_config_path
        )
        if progress_callback is not None:
            progress_callback("步骤 3/5 检查 agent 模型")
        agent_model_files = [
            ensure_agent_models_file(path)
            for path in detect_openclaw_agent_model_files(root)
        ]

    resolved_opencode_config_path = opencode_config_path
    resolved_opencode_auth_path = opencode_auth_path
    if variant_requires_opencode_config():
        if progress_callback is not None:
            progress_callback("步骤 4/5 检查 OpenCode 配置")
        resolved_opencode_config_path = ensure_opencode_config(opencode_config_path)
        resolved_opencode_auth_path = ensure_opencode_auth_file(opencode_auth_path)
    if progress_callback is not None:
        progress_callback("步骤 5/5 验证初始化结果")
    verification = verify_initialized_environment(
        root=root,
        openclaw_config_path=resolved_openclaw_config_path,
        opencode_config_path=resolved_opencode_config_path,
        opencode_auth_path=resolved_opencode_auth_path,
        require_marker=False,
    )
    set_init_status(root, completed=True, verified=bool(verification.get("ok")))
    verification = verify_initialized_environment(
        root=root,
        openclaw_config_path=resolved_openclaw_config_path,
        opencode_config_path=resolved_opencode_config_path,
        opencode_auth_path=resolved_opencode_auth_path,
    )
    return {
        "root": root,
        "openclaw_config_path": resolved_openclaw_config_path,
        "opencode_config_path": resolved_opencode_config_path,
        "opencode_auth_path": resolved_opencode_auth_path,
        "agent_model_files": agent_model_files,
        "agent_count": len(agent_model_files),
        "verification": verification,
    }


def ensure_environment_ready_for_menu(
    root: Path = ROOT,
    openclaw_config_path: Path | None = None,
    opencode_config_path: Path = OPENCODE_CONFIG_FILE,
    opencode_auth_path: Path = OPENCODE_AUTH_FILE,
    verify_fn: Callable[..., JsonDict] = verify_initialized_environment,
    initialize_fn: Callable[..., JsonDict] = initialize_environment,
    run_with_loading_fn: Callable[..., Any] = run_with_loading,
    show_error_fn: Callable[[str, str | None], None] = show_status_screen,
    show_success_fn: Callable[[str, str | None], None] = show_status_screen,
) -> bool:
    in_place_success = {"done": False}

    def finish_in_same_panel(status: Any, summary: Any) -> None:
        verification = (
            summary.get("verification") if isinstance(summary, dict) else None
        )
        if not isinstance(verification, dict) or not verification.get("ok"):
            return
        if hasattr(status, "complete_success"):
            detail = (
                str(verification.get("detail") or "").strip()
                or "OpenClAW / OpenCode 初始化检测通过。"
            )
            status.complete_success("初始化完成", detail)
            in_place_success["done"] = True

    try:
        summary = run_with_loading_fn(
            "正在初始化环境...",
            lambda progress_callback=None: initialize_fn(
                root=root,
                openclaw_config_path=openclaw_config_path,
                opencode_config_path=opencode_config_path,
                opencode_auth_path=opencode_auth_path,
                progress_callback=progress_callback,
            ),
            None,
            finish_in_same_panel,
        )
    except Exception as exc:
        show_error_fn("初始化失败", str(exc))
        return False
    if not isinstance(summary, dict):
        show_error_fn(
            "初始化失败",
            "初始化返回结果无效，请检查 OpenClAW / OpenCode 配置后重新启动程序。",
        )
        return False
    verification = summary.get("verification")
    if not isinstance(verification, dict):
        verification = verify_fn(
            root=root,
            openclaw_config_path=openclaw_config_path,
            opencode_config_path=opencode_config_path,
            opencode_auth_path=opencode_auth_path,
        )
    if verification.get("ok"):
        success_detail = (
            str(verification.get("detail") or "").strip()
            or "OpenClAW / OpenCode 初始化检测通过。"
        )
        if not in_place_success["done"]:
            show_success_fn("初始化完成", success_detail)
        return True
    detail = None
    if isinstance(verification, dict):
        detail = str(verification.get("detail") or "").strip() or None
    show_error_fn(
        "初始化失败",
        detail or "初始化未通过验证，请检查 OpenClAW / OpenCode 配置后重新启动程序。",
    )
    return False


def normalize_saved_profile(profile: JsonDict) -> JsonDict:
    return {
        "type": "oauth",
        "provider": PROVIDER_KEY,
        "access": str(profile.get("access", "") or ""),
        "refresh": str(profile.get("refresh", "") or ""),
        "expires": int(profile.get("expires", 0) or 0),
        "accountId": str(profile.get("accountId", "") or ""),
        "email": str(profile.get("email", "") or ""),
        "displayName": str(profile.get("displayName", "") or ""),
    }


def profile_credentials_changed(before: JsonDict, after: JsonDict) -> bool:
    keys = ("access", "refresh", "expires", "accountId")
    for key in keys:
        if before.get(key) != after.get(key):
            return True
    return False


def merge_refreshed_profile(raw_profile: JsonDict, refreshed_profile: JsonDict) -> bool:
    changed = False
    for key in ("access", "refresh", "expires", "accountId"):
        new_value = refreshed_profile.get(key)
        if raw_profile.get(key) != new_value:
            raw_profile[key] = new_value
            changed = True
    return changed


def get_account_display_name(alias: str, profile: JsonDict) -> str:
    display_name = str(profile.get("displayName", "") or "").strip()
    return display_name or alias


def sanitize_display_name(value: str) -> str:
    return "".join(ch for ch in value if ch >= " " and ch != "\x7f").strip()


def get_selected_display_name(root: Path = ROOT) -> str | None:
    alias = get_selected_alias(root)
    if not alias:
        return None
    store = load_store(root)
    profile = store.get("accounts", {}).get(alias, {})
    return get_account_display_name(alias, profile if isinstance(profile, dict) else {})


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64).rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )
    return verifier, challenge


def create_oauth_state() -> str:
    return secrets.token_hex(16)


def build_login_url(state: str, challenge: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": OAUTH_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "pi",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def decode_jwt_payload(token: str) -> JsonDict:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode((payload + padding).encode("utf-8"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def start_login_session(
    root: Path = ROOT,
    create_pkce_fn: Callable[[], tuple[str, str]] = create_pkce_pair,
    create_state_fn: Callable[[], str] = create_oauth_state,
) -> JsonDict:
    verifier, challenge = create_pkce_fn()
    state = create_state_fn()
    session = {
        "state": state,
        "verifier": verifier,
        "createdAt": now_iso(),
        "url": build_login_url(state, challenge),
    }
    write_json(login_session_file(root), session)
    return session


def complete_login_session(
    root: Path,
    callback_url: str,
    requests_post: Callable[..., Any] | None = None,
    timeout: int = 10,
) -> JsonDict:
    session = read_json(login_session_file(root))
    state = str(session.get("state", "") or "")
    verifier = str(session.get("verifier", "") or "")
    if not state or not verifier:
        raise ValueError("当前没有待完成的登录会话，请先重新发起登录")

    parsed_url = urlparse(callback_url.strip())
    params = parse_qs(parsed_url.query)
    callback_state = (params.get("state") or [""])[0]
    code = (params.get("code") or [""])[0]
    if callback_state and callback_state != state:
        raise ValueError("登录回调和当前会话不匹配，请重新发起登录")
    if not code:
        raise ValueError("回调地址里没有授权码")

    post = requests_post or requests.post
    response = post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    access = str(payload.get("access_token", "") or "")
    refresh = str(payload.get("refresh_token", "") or "")
    expires_in = int(payload.get("expires_in", 0) or 0)
    if not access or not refresh or expires_in <= 0:
        raise ValueError("OpenAI 返回的登录结果不完整")

    jwt_payload = decode_jwt_payload(access)
    auth_payload = (
        jwt_payload.get("https://api.openai.com/auth")
        if isinstance(jwt_payload, dict)
        else {}
    )
    profile_payload = (
        jwt_payload.get("https://api.openai.com/profile")
        if isinstance(jwt_payload, dict)
        else {}
    )
    account_id = str((auth_payload or {}).get("chatgpt_account_id", "") or "")
    if not account_id:
        raise ValueError("无法从 access token 解析账号 ID")

    session_path = login_session_file(root)
    if session_path.exists():
        session_path.unlink()
    return normalize_saved_profile(
        {
            "access": access,
            "refresh": refresh,
            "expires": current_time_ms() + expires_in * 1000,
            "accountId": account_id,
            "email": str((profile_payload or {}).get("email", "") or ""),
        }
    )


def get_selected_alias(root: Path = ROOT) -> str | None:
    store = load_store(root)
    active = store.get("active")
    accounts = store.get("accounts", {})
    if isinstance(active, str) and active in accounts:
        return active
    aliases = [alias for alias in accounts.keys() if isinstance(alias, str)]
    return aliases[0] if aliases else None


def profile_matches(left: JsonDict, right: JsonDict) -> bool:
    return (
        left.get("provider") == right.get("provider") == PROVIDER_KEY
        and left.get("accountId", "") == right.get("accountId", "")
        and left.get("refresh", "") == right.get("refresh", "")
    )


def detect_current_alias(root: Path = ROOT) -> str | None:
    current = extract_current_profile(root)
    store = load_store(root)
    for alias, profile in store.get("accounts", {}).items():
        if isinstance(profile, dict) and profile_matches(current, profile):
            return alias
    return None


def parse_accounts_catalog(payload: JsonDict) -> list[JsonDict]:
    accounts = payload.get("accounts")
    ordering = payload.get("account_ordering")
    if not isinstance(accounts, dict):
        return []
    keys: list[str] = []
    if isinstance(ordering, list):
        keys.extend(
            [item for item in ordering if isinstance(item, str) and item in accounts]
        )
    for key in accounts.keys():
        if isinstance(key, str) and key not in keys:
            keys.append(key)

    result: list[JsonDict] = []
    for key in keys:
        item = accounts.get(key)
        if not isinstance(item, dict):
            continue
        account = item.get("account")
        if not isinstance(account, dict):
            continue
        structure = str(account.get("structure", "") or "")
        result.append(
            {
                "key": key,
                "accountId": str(account.get("account_id", "") or ""),
                "name": str(account.get("name", "") or "").strip()
                or ("个人空间" if structure == "personal" else key),
                "structure": structure or "unknown",
                "planType": str(account.get("plan_type", "") or "") or "unknown",
                "isPersonal": structure == "personal",
                "isDeactivated": bool(account.get("is_deactivated", False)),
            }
        )
    return result


def progress_bar(used_percent: float, width: int = 18) -> str:
    bounded = max(0.0, min(100.0, float(used_percent)))
    remaining = 100.0 - bounded
    filled = round((remaining / 100.0) * width)
    return "█" * filled + "░" * max(0, width - filled)


def quota_style_name(remaining_percent: float) -> str:
    value = max(0.0, min(100.0, float(remaining_percent)))
    if value <= 15.0:
        return "red"
    if value <= 45.0:
        return "yellow"
    return "green"


def colorize_progress_bar(bar: str, style: str) -> str:
    return f"[{style}]{bar}[/{style}]"


def build_login_helper_env(output_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENCODE_LOGIN_OUTPUT_PATH"] = str(output_path)
    env["OPENCODE_LOGIN_INTERACTIVE"] = "1"
    if BUNDLED_OPENAI_CODEX_HELPER_ENTRY.exists():
        env["OPENCLAW_LOGIN_MODULE_ENTRY"] = str(BUNDLED_OPENAI_CODEX_HELPER_ENTRY)
    return env


def resolve_node_command() -> str:
    if BUNDLED_NODE_EXE.exists():
        return str(BUNDLED_NODE_EXE)
    found = shutil.which("node")
    if found:
        return found
    return "node"


def login_helper_available(helper_path: Path = LOGIN_HELPER) -> bool:
    if not helper_path.exists():
        return False
    if BUNDLED_NODE_EXE.exists():
        return True
    return shutil.which("node") is not None


def build_openclaw_command_with_entrypoint(
    node_command: str, entrypoint: Path
) -> list[str]:
    return [
        node_command,
        str(entrypoint),
        "models",
        "auth",
        "login",
        "--provider",
        "openai-codex",
    ]


def build_official_login_command(executable: str = "openclaw") -> list[str]:
    return [executable, "models", "auth", "login", "--provider", "openai-codex"]


def resolve_official_login_command(appdata: str | None = None) -> list[str]:
    if BUNDLED_OPENCLAW_ENTRY.exists():
        return build_openclaw_command_with_entrypoint(
            resolve_node_command(), BUNDLED_OPENCLAW_ENTRY
        )
    resolved_appdata = appdata if appdata is not None else os.environ.get("APPDATA", "")
    if resolved_appdata:
        npm_root = Path(resolved_appdata) / "npm"
        entrypoint = npm_root / "node_modules" / "openclaw" / "openclaw.mjs"
        if entrypoint.exists():
            node_executable = npm_root / "node.exe"
            node_command = (
                str(node_executable)
                if node_executable.exists()
                else resolve_node_command()
            )
            return build_openclaw_command_with_entrypoint(node_command, entrypoint)
    return build_official_login_command()


def strip_ansi_codes(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)


def extract_json_object(text: str) -> str | None:
    cleaned = strip_ansi_codes(text)
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    return None


def official_provider_available(provider_id: str = PROVIDER_KEY) -> bool:
    try:
        ensure_openclaw_config(ROOT)
        command = ["openclaw", "plugins", "list", "--json"]
        if BUNDLED_OPENCLAW_ENTRY.exists():
            command = [
                resolve_node_command(),
                str(BUNDLED_OPENCLAW_ENTRY),
                "plugins",
                "list",
                "--json",
            ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    payload_text = extract_json_object(result.stdout or "")
    if not payload_text:
        return False
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return False
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        return False
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        provider_ids = plugin.get("providerIds")
        if isinstance(provider_ids, list) and provider_id in provider_ids:
            return (
                bool(plugin.get("enabled", False))
                and str(plugin.get("status", "")) == "loaded"
            )
    return False


def run_interactive_command(command: list[str]) -> None:
    if not sys.stdin.isatty():
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=result.returncode,
                cmd=command,
                output=result.stdout,
                stderr=result.stderr,
            )
        return
    show_cursor()
    try:
        if os.name == "nt":
            command_line = subprocess.list2cmdline(command)
            return_code = os.system(command_line)
        else:
            return_code = subprocess.run(command, check=False).returncode
    finally:
        hide_cursor()
    if return_code != 0:
        raise subprocess.CalledProcessError(returncode=return_code, cmd=command)


def run_openai_login_helper(helper_path: Path = LOGIN_HELPER) -> JsonDict:
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "openai-login-result.json"
        subprocess.run(
            [resolve_node_command(), str(helper_path)],
            check=True,
            text=True,
            env=build_login_helper_env(output_path),
        )
        if not output_path.exists():
            raise ValueError("登录流程没有产出凭据文件")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Login helper returned invalid payload")
        return normalize_saved_profile(payload)


def add_account_via_login(
    root: Path,
    alias: str,
    login_fn: Callable[[], JsonDict] = run_openai_login_helper,
) -> str:
    profile = normalize_saved_profile(login_fn())
    if not profile["access"] or not profile["refresh"] or not profile["accountId"]:
        raise ValueError("Login did not return complete oauth credentials")
    store = load_store(root)
    store["accounts"][alias] = {
        **profile,
        "savedAt": now_iso(),
    }
    if not store.get("active"):
        store["active"] = alias
    save_store(store, root)
    return alias


def add_account_via_login_helper(
    root: Path,
    login_fn: Callable[[], JsonDict] = run_openai_login_helper,
    upsert_profile_fn: Callable[[Path, JsonDict, str | None], str] | None = None,
) -> str:
    profile = normalize_saved_profile(login_fn())
    if not profile["access"] or not profile["refresh"] or not profile["accountId"]:
        raise ValueError("登录流程没有返回完整账号凭据")
    upsert_fn = upsert_profile_fn or upsert_account_profile
    return upsert_fn(root, profile, "login-helper")


def find_existing_alias_for_profile(root: Path, profile: JsonDict) -> str | None:
    store = load_store(root)
    account_id = str(profile.get("accountId", "") or "")
    refresh = str(profile.get("refresh", "") or "")
    for alias, existing in store.get("accounts", {}).items():
        if not isinstance(alias, str) or not isinstance(existing, dict):
            continue
        if account_id and existing.get("accountId") == account_id:
            return alias
        if refresh and existing.get("refresh") == refresh:
            return alias
    return None


def upsert_account_profile(
    root: Path, profile: JsonDict, source: str | None = None
) -> str:
    store = load_store(root)
    alias = find_existing_alias_for_profile(root, profile) or make_alias_from_profile(
        root, profile
    )
    existing = store.get("accounts", {}).get(alias)
    payload: JsonDict = {
        **profile,
        "savedAt": now_iso(),
    }
    if (
        isinstance(existing, dict)
        and existing.get("displayName")
        and not payload.get("displayName")
    ):
        payload["displayName"] = existing.get("displayName")
    if source:
        payload["source"] = source
    store["accounts"][alias] = payload
    if not store.get("active"):
        store["active"] = alias
    save_store(store, root)
    return alias


def make_alias_from_profile(root: Path, profile: JsonDict) -> str:
    store = load_store(root)
    accounts = store.get("accounts", {})
    email = str(profile.get("email", "") or "").strip()
    if email and "@" in email:
        base = email.split("@", 1)[0].strip().lower()
    else:
        account_id = str(profile.get("accountId", "") or "").strip()
        base = f"account-{account_id[:8]}" if account_id else "account"
    base = base or "account"
    alias = base
    index = 2
    while alias in accounts:
        alias = f"{base}-{index}"
        index += 1
    return alias


def set_account_display_name(root: Path, alias: str, display_name: str) -> None:
    store = load_store(root)
    accounts = store.get("accounts", {})
    profile = accounts.get(alias)
    if not isinstance(profile, dict):
        raise ValueError(f"未找到账号别名：{alias}")
    cleaned_name = sanitize_display_name(display_name)
    if not cleaned_name:
        raise ValueError("名称不能为空")
    profile["displayName"] = cleaned_name
    save_store(store, root)


def add_account_auto(
    root: Path,
    login_fn: Callable[[], JsonDict] = run_openai_login_helper,
) -> str:
    profile = normalize_saved_profile(login_fn())
    if not profile["access"] or not profile["refresh"] or not profile["accountId"]:
        raise ValueError("登录后没有拿到完整凭据")
    return upsert_account_profile(root, profile)


def import_current_openclaw_login(
    target_root: Path,
    source_root: Path = ROOT,
) -> str:
    profile = normalize_saved_profile(extract_current_profile(source_root))
    if not profile["access"] or not profile["refresh"] or not profile["accountId"]:
        raise ValueError("当前没有可导入的完整登录态")
    return upsert_account_profile(target_root, profile, source="openclaw-import")


def login_via_official_openclaw(
    target_root: Path,
    run_command_fn: Callable[[list[str]], None] = run_interactive_command,
    import_fn: Callable[[Path, Path], str] = import_current_openclaw_login,
    source_root: Path = ROOT,
) -> str:
    ensure_openclaw_config(source_root)
    command = resolve_official_login_command()
    try:
        run_command_fn(command)
    except subprocess.CalledProcessError as exc:
        stderr_text = str(getattr(exc, "stderr", "") or "").strip()
        if "interactive TTY" in stderr_text:
            raise ValueError(
                "当前环境没有可用的交互式终端，官方登录无法继续。请直接从终端里运行这个脚本后再试。"
            ) from exc
        message = f"官方登录失败（退出码 {exc.returncode}）"
        if stderr_text:
            message = f"{message}：{stderr_text.splitlines()[-1]}"
        raise ValueError(message) from exc
    return import_fn(target_root, source_root)


def add_account_via_manual_callback_fallback(
    root: Path,
    start_login_fn: Callable[[], JsonDict],
    prompt_callback_fn: Callable[[str], str | None],
    finish_login_fn: Callable[[str], JsonDict],
    upsert_profile_fn: Callable[[Path, JsonDict, str | None], str],
) -> str:
    session = start_login_fn()
    authorize_url = str(session.get("authorizeUrl") or session.get("url") or "").strip()
    if not authorize_url:
        raise ValueError("手动登录兜底失败：没有拿到可用的授权链接")
    clear_screen()
    console.print(
        Panel.fit(
            "请在浏览器中打开下面这个链接完成登录：\n\n"
            f"{authorize_url}\n\n"
            "登录完成后，把浏览器最后跳转到的 localhost 回调地址完整贴回来",
            border_style="cyan",
            title=f"{APP_NAME} 手动登录",
        )
    )
    callback_url = prompt_callback_fn("请粘贴浏览器最后跳转到的 localhost 回调地址")
    if not callback_url:
        raise ValueError("你已取消手动回调登录")
    profile = finish_login_fn(str(callback_url).strip())
    return upsert_profile_fn(root, profile, "manual-oauth-fallback")


def format_window_label(limit_window_seconds: int, fallback: str) -> str:
    seconds = max(int(limit_window_seconds or 0), 0)
    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return fallback


def format_dashboard_error(error: Exception) -> str:
    if isinstance(error, requests.ReadTimeout):
        return "请求超时，已保留上次数据；可稍后再刷新"
    if isinstance(error, requests.ConnectTimeout):
        return "连接超时，已保留上次数据；可稍后再刷新"
    if isinstance(error, requests.ConnectionError):
        return "网络连接失败，可能未开启 VPN/代理或当前节点不稳定；已保留上次数据"
    if isinstance(error, requests.HTTPError):
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        if status_code == 403:
            return "接口拒绝访问（403），工作组信息可能暂时不可读"
        if status_code == 401:
            return "登录态已失效（401），请重新登录后再试"
        if status_code:
            return f"接口请求失败（{status_code}）"
    return str(error)


def get_dashboard_http_status(error: Exception) -> int | None:
    if not isinstance(error, requests.HTTPError):
        return None
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    return int(status_code) if isinstance(status_code, int) else None


def is_auth_dashboard_error(error: Exception) -> bool:
    return get_dashboard_http_status(error) in (401, 403)


def is_auth_refresh_endpoint_error(error: Exception) -> bool:
    if not isinstance(error, requests.HTTPError):
        return False
    status_code = get_dashboard_http_status(error)
    if status_code not in (400, 401, 403):
        return False
    response_url = str(getattr(getattr(error, "response", None), "url", "") or "")
    if not response_url:
        return False
    return response_url.startswith(TOKEN_URL)


def has_dashboard_snapshot(row: JsonDict | None) -> bool:
    if not isinstance(row, dict):
        return False
    return bool(row.get("windows") or row.get("groups"))


def get_dashboard_auth_error_state(
    previous: JsonDict | None, error: Exception
) -> JsonDict:
    status_code = get_dashboard_http_status(error)
    now_ms = current_time_ms()
    if status_code is None:
        return {"statusCode": None, "count": 0, "firstAtMs": None}
    previous_status = (
        previous.get("_authIssueStatus") if isinstance(previous, dict) else None
    )
    previous_count = (
        int(previous.get("_authIssueCount") or 0) if isinstance(previous, dict) else 0
    )
    previous_first_at = (
        previous.get("_authIssueFirstAtMs") if isinstance(previous, dict) else None
    )
    if previous_status == status_code and has_dashboard_snapshot(previous):
        return {
            "statusCode": status_code,
            "count": max(1, previous_count + 1),
            "firstAtMs": int(previous_first_at)
            if isinstance(previous_first_at, int)
            else now_ms,
        }
    return {"statusCode": status_code, "count": 1, "firstAtMs": now_ms}


def format_dashboard_auth_warning(status_code: int, attempt: int) -> str:
    if status_code == 401:
        return (
            f"鉴权接口临时波动，已沿用上次额度数据，本次先不判定账号失效"
            f"（连续异常 {attempt}/{DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS} 次）"
        )
    if status_code == 403:
        return (
            f"鉴权接口临时波动，已沿用上次额度数据，本次先不判定工作组异常"
            f"（连续异常 {attempt}/{DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS} 次）"
        )
    return f"接口临时请求失败（{status_code}），已沿用上次额度数据"


def format_dashboard_auth_failure(status_code: int, attempt: int) -> str:
    if status_code == 401:
        return f"鉴权接口连续异常（已连续 {attempt} 次），登录态大概率已失效，请重新登录后再试"
    if status_code == 403:
        return f"鉴权接口连续异常（已连续 {attempt} 次），工作组信息持续不可读，请稍后再试或重新登录"
    return f"接口连续请求失败（{status_code}）"


def format_dashboard_auth_blocked_error(remaining_ms: int) -> str:
    return f"登录凭证需要重新登录，已暂停自动检测（剩余 {format_compact_duration_ms(remaining_ms)}）"


def is_transient_dashboard_error(error: Exception) -> bool:
    if isinstance(
        error, (requests.ReadTimeout, requests.ConnectTimeout, requests.ConnectionError)
    ):
        return True
    if isinstance(error, requests.HTTPError):
        status_code = get_dashboard_http_status(error)
        return status_code not in (401, 403)
    return isinstance(error, requests.RequestException)


def refresh_openai_codex_token(
    profile: JsonDict,
    requests_post: Callable[..., Any] | None = None,
    timeout: int = DASHBOARD_REQUEST_TIMEOUT_SECONDS,
) -> JsonDict:
    post = requests_post or requests.post
    refresh_token = str(profile.get("refresh", "") or "").strip()
    if not refresh_token:
        raise ValueError("Refresh token missing")

    response = post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    access = str(payload.get("access_token", "") or "").strip()
    refresh = str(payload.get("refresh_token", "") or "").strip() or refresh_token
    expires_in = int(payload.get("expires_in", 0) or 0)
    if not access or expires_in <= 0:
        raise ValueError("Invalid refresh response")

    profile["access"] = access
    profile["refresh"] = refresh
    profile["expires"] = int(current_time_ms() + expires_in * 1000)
    return profile


def current_time_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def fetch_codex_usage(
    profile: JsonDict,
    requests_get: Callable[..., Any] | None = None,
    requests_post: Callable[..., Any] | None = None,
    timeout: int = DASHBOARD_REQUEST_TIMEOUT_SECONDS,
) -> JsonDict:
    get = requests_get or requests.get
    headers = lambda: {
        "Authorization": f"Bearer {profile.get('access', '')}",
        "User-Agent": "CodexBar",
        "Accept": "application/json",
        **(
            {"ChatGPT-Account-Id": profile["accountId"]}
            if profile.get("accountId")
            else {}
        ),
    }

    response = get(USAGE_URL, headers=headers(), timeout=timeout)
    if getattr(response, "status_code", 0) == 401:
        refresh_openai_codex_token(
            profile, requests_post=requests_post, timeout=timeout
        )
        response = get(USAGE_URL, headers=headers(), timeout=timeout)
    response.raise_for_status()
    data = response.json()

    windows: list[JsonDict] = []
    primary = data.get("rate_limit", {}).get("primary_window")
    if isinstance(primary, dict):
        windows.append(
            {
                "label": format_window_label(
                    primary.get("limit_window_seconds", 0), "Primary"
                ),
                "usedPercent": float(primary.get("used_percent", 0) or 0),
                "resetAt": int(primary["reset_at"] * 1000)
                if primary.get("reset_at")
                else None,
            }
        )

    secondary = data.get("rate_limit", {}).get("secondary_window")
    if isinstance(secondary, dict):
        windows.append(
            {
                "label": format_window_label(
                    secondary.get("limit_window_seconds", 0), "Secondary"
                ),
                "usedPercent": float(secondary.get("used_percent", 0) or 0),
                "resetAt": int(secondary["reset_at"] * 1000)
                if secondary.get("reset_at")
                else None,
            }
        )

    return {"plan": data.get("plan_type"), "windows": windows, "raw": data}


def fetch_account_catalog(
    profile: JsonDict,
    requests_get: Callable[..., Any] | None = None,
    timeout: int = DASHBOARD_REQUEST_TIMEOUT_SECONDS,
) -> list[JsonDict]:
    get = requests_get or requests.get
    response = get(
        "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27",
        headers={
            "Authorization": f"Bearer {profile.get('access', '')}",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "oai-client-version": "prod-eddc2f6ff65fee2d0d6439e379eab94fe3047f72",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_accounts_catalog(response.json())


def fallback_group_from_profile(profile: JsonDict, usage: JsonDict) -> JsonDict:
    return {
        "key": profile.get("accountId", "current") or "current",
        "accountId": profile.get("accountId", "") or "",
        "name": "当前工作组",
        "structure": "workspace",
        "planType": usage.get("plan") or "unknown",
        "isPersonal": (usage.get("plan") or "") == "free",
        "windows": usage.get("windows") or [],
    }


def build_dashboard_row_for_account(
    alias: str,
    raw_profile: JsonDict,
    current_alias: str | None,
    fetch_usage_fn: Callable[..., JsonDict],
    fetch_catalog_fn: Callable[..., list[JsonDict]],
    previous: JsonDict | None = None,
    on_profile_refreshed: Callable[[str, JsonDict], None] | None = None,
    ignore_auth_block: bool = False,
) -> JsonDict:
    baseline_profile = normalize_saved_profile(raw_profile)
    profile = normalize_saved_profile(raw_profile)
    previous_snapshot = previous if isinstance(previous, dict) else {}
    started_at_ms = current_time_ms()
    row: JsonDict = {
        "alias": alias,
        "displayName": get_account_display_name(alias, raw_profile),
        "accountId": profile["accountId"] or "未知",
        "isCurrent": alias == current_alias,
        "plan": "未知",
        "windows": [],
        "groups": [],
        "error": None,
        "warning": None,
        "_authIssueStatus": None,
        "_authIssueCount": 0,
        "_authIssueFirstAtMs": None,
        "_authBlockedUntilMs": None,
        "_authBlockedRefresh": None,
        "_lastRefreshedAtMs": None,
        "_nextRefreshAtMs": None,
        "_dailyRefreshAttemptDay": None,
        "_dailyRefreshAttemptAtMs": None,
        "_dailyRefreshSuccessDay": None,
        "_refreshedThisCycle": False,
    }
    blocked_until_ms = int(previous_snapshot.get("_authBlockedUntilMs") or 0)
    blocked_refresh = str(previous_snapshot.get("_authBlockedRefresh") or "")
    current_refresh = str(profile.get("refresh") or "")
    now_ms = current_time_ms()
    if not ignore_auth_block and (
        blocked_until_ms > now_ms
        and blocked_refresh
        and blocked_refresh == current_refresh
    ):
        row["plan"] = previous_snapshot.get("plan", "未知")
        row["windows"] = list(previous_snapshot.get("windows") or [])
        row["groups"] = list(previous_snapshot.get("groups") or [])
        row["error"] = format_dashboard_auth_blocked_error(blocked_until_ms - now_ms)
        row["_authIssueStatus"] = previous_snapshot.get("_authIssueStatus")
        row["_authIssueCount"] = int(previous_snapshot.get("_authIssueCount") or 0)
        row["_authIssueFirstAtMs"] = previous_snapshot.get("_authIssueFirstAtMs")
        row["_authBlockedUntilMs"] = blocked_until_ms
        row["_authBlockedRefresh"] = blocked_refresh
        row["_lastRefreshedAtMs"] = previous_snapshot.get("_lastRefreshedAtMs")
        row["_nextRefreshAtMs"] = blocked_until_ms
        row["_dailyRefreshAttemptDay"] = previous_snapshot.get(
            "_dailyRefreshAttemptDay"
        )
        row["_dailyRefreshAttemptAtMs"] = previous_snapshot.get(
            "_dailyRefreshAttemptAtMs"
        )
        row["_dailyRefreshSuccessDay"] = previous_snapshot.get(
            "_dailyRefreshSuccessDay"
        )
        return row
    row["_dailyRefreshAttemptDay"] = current_local_day_key(started_at_ms)
    row["_dailyRefreshAttemptAtMs"] = started_at_ms
    row["_refreshedThisCycle"] = True
    try:
        usage = fetch_usage_fn(profile)
        row["plan"] = usage.get("plan") or "未知"
        row["windows"] = usage.get("windows") or []
        try:
            groups = fetch_catalog_fn(profile)
        except Exception:
            groups = []
        if not groups:
            groups = [fallback_group_from_profile(profile, usage)]
        row["groups"] = [
            {
                **group,
                "windows": usage.get("windows") or []
                if group.get("accountId") == profile.get("accountId")
                else group.get("windows") or [],
            }
            for group in groups
        ]
        row["_dailyRefreshSuccessDay"] = current_local_day_key(started_at_ms)
    except Exception as exc:
        formatted_error = format_dashboard_error(exc)
        auth_error_state = get_dashboard_auth_error_state(previous, exc)
        if is_auth_refresh_endpoint_error(exc):
            block_until_ms = current_time_ms() + DASHBOARD_AUTH_HARD_FAILURE_COOLDOWN_MS
            row["plan"] = previous_snapshot.get("plan", "未知")
            row["windows"] = list(previous_snapshot.get("windows") or [])
            row["groups"] = list(previous_snapshot.get("groups") or [])
            row["error"] = format_dashboard_auth_blocked_error(
                DASHBOARD_AUTH_HARD_FAILURE_COOLDOWN_MS
            )
            row["_authIssueStatus"] = auth_error_state["statusCode"]
            row["_authIssueCount"] = max(
                DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS + 1,
                int(auth_error_state["count"]),
            )
            row["_authIssueFirstAtMs"] = auth_error_state["firstAtMs"]
            row["_authBlockedUntilMs"] = block_until_ms
            row["_authBlockedRefresh"] = current_refresh
        elif is_auth_dashboard_error(exc) and has_dashboard_snapshot(previous):
            row["_authIssueStatus"] = auth_error_state["statusCode"]
            row["_authIssueCount"] = auth_error_state["count"]
            row["_authIssueFirstAtMs"] = auth_error_state["firstAtMs"]
            if int(auth_error_state["count"]) <= DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS:
                row["plan"] = previous_snapshot.get("plan", "未知")
                row["windows"] = list(previous_snapshot.get("windows") or [])
                row["groups"] = list(previous_snapshot.get("groups") or [])
                row["warning"] = format_dashboard_auth_warning(
                    int(auth_error_state["statusCode"]),
                    int(auth_error_state["count"]),
                )
            else:
                row["error"] = format_dashboard_auth_failure(
                    int(auth_error_state["statusCode"]),
                    int(auth_error_state["count"]),
                )
                row["groups"] = []
        elif is_transient_dashboard_error(exc) and has_dashboard_snapshot(previous):
            row["plan"] = previous_snapshot.get("plan", "未知")
            row["windows"] = list(previous_snapshot.get("windows") or [])
            row["groups"] = list(previous_snapshot.get("groups") or [])
            row["warning"] = formatted_error
        else:
            row["error"] = formatted_error
            row["groups"] = []
    finally:
        if on_profile_refreshed is not None and profile_credentials_changed(
            baseline_profile, profile
        ):
            on_profile_refreshed(alias, profile)
    row["_lastRefreshedAtMs"] = started_at_ms
    row["_nextRefreshAtMs"] = compute_dashboard_row_next_refresh_at(
        row,
        is_current=alias == current_alias,
        now_ms=started_at_ms,
    )
    return row


def build_dashboard_rows(
    root: Path = ROOT,
    fetch_usage_fn: Callable[..., JsonDict] = fetch_codex_usage,
    fetch_catalog_fn: Callable[..., list[JsonDict]] = fetch_account_catalog,
    progress_fn: Callable[[str, int, int], None] | None = None,
    previous_rows: list[JsonDict] | None = None,
    max_workers: int = MAX_DASHBOARD_FETCH_WORKERS,
    force_full_refresh: bool = False,
) -> list[JsonDict]:
    store = load_store(root)
    accounts = store.get("accounts", {})
    current_alias = get_selected_alias(root)
    resolved_previous_rows = list(previous_rows or load_dashboard_snapshot_rows(root))
    refreshed_profiles: dict[str, JsonDict] = {}
    refreshed_profiles_lock = threading.Lock()

    def record_refreshed_profile(alias: str, refreshed: JsonDict) -> None:
        with refreshed_profiles_lock:
            refreshed_profiles[alias] = normalize_saved_profile(refreshed)

    previous_rows_by_alias = {
        str(row.get("alias") or ""): row
        for row in resolved_previous_rows
        if isinstance(row, dict) and row.get("alias")
    }
    rows: list[JsonDict] = []
    account_items = [
        (alias, raw_profile)
        for alias, raw_profile in accounts.items()
        if isinstance(alias, str) and isinstance(raw_profile, dict)
    ]
    total_accounts = len(account_items)
    now_ms = current_time_ms()
    today_key = current_local_day_key(now_ms)

    def build_cached_row(
        alias: str, raw_profile: JsonDict, previous: JsonDict
    ) -> JsonDict:
        profile = normalize_saved_profile(raw_profile)
        cached_row = {
            "alias": alias,
            "displayName": get_account_display_name(alias, raw_profile),
            "accountId": profile["accountId"] or "未知",
            "isCurrent": alias == current_alias,
            "plan": previous.get("plan", "未知"),
            "windows": list(previous.get("windows") or []),
            "groups": list(previous.get("groups") or []),
            "error": previous.get("error"),
            "warning": previous.get("warning"),
            "_authIssueStatus": previous.get("_authIssueStatus"),
            "_authIssueCount": previous.get("_authIssueCount", 0),
            "_authIssueFirstAtMs": previous.get("_authIssueFirstAtMs"),
            "_authBlockedUntilMs": previous.get("_authBlockedUntilMs"),
            "_authBlockedRefresh": previous.get("_authBlockedRefresh"),
            "_lastRefreshedAtMs": previous.get("_lastRefreshedAtMs"),
            "_nextRefreshAtMs": previous.get("_nextRefreshAtMs"),
            "_dailyRefreshAttemptDay": previous.get("_dailyRefreshAttemptDay"),
            "_dailyRefreshAttemptAtMs": previous.get("_dailyRefreshAttemptAtMs"),
            "_dailyRefreshSuccessDay": previous.get("_dailyRefreshSuccessDay"),
            "_refreshedThisCycle": False,
        }
        if not isinstance(cached_row.get("_nextRefreshAtMs"), int):
            cached_row["_nextRefreshAtMs"] = compute_dashboard_row_next_refresh_at(
                cached_row,
                is_current=alias == current_alias,
                now_ms=now_ms,
            )
        return cached_row

    scheduled_aliases: set[str] = set()
    if force_full_refresh:
        scheduled_aliases = {
            alias for alias, _raw_profile in account_items if isinstance(alias, str)
        }
    elif total_accounts <= 1 or not previous_rows_by_alias:
        scheduled_aliases = {
            alias for alias, _raw_profile in account_items if isinstance(alias, str)
        }
    else:
        due_background: list[tuple[tuple[int, float, int], int, str]] = []
        for alias, raw_profile in account_items:
            previous = previous_rows_by_alias.get(alias)
            if alias == current_alias:
                scheduled_aliases.add(alias)
                continue
            if not isinstance(previous, dict) or not previous:
                scheduled_aliases.add(alias)
                continue
            blocked_until_ms = int(previous.get("_authBlockedUntilMs") or 0)
            blocked_refresh = str(previous.get("_authBlockedRefresh") or "")
            current_refresh = str(raw_profile.get("refresh") or "")
            if (
                blocked_until_ms > now_ms
                and blocked_refresh
                and blocked_refresh == current_refresh
            ):
                continue
            if str(previous.get("_dailyRefreshSuccessDay") or "") != today_key:
                due_background.append(
                    (
                        get_dashboard_row_refresh_priority(previous),
                        int(previous.get("_dailyRefreshAttemptAtMs") or 0),
                        alias,
                    )
                )
                continue
            reset_7d = get_window_reset_at_ms(previous, "7d")
            remaining_5h = get_window_remaining_value(previous, "5h")
            if (
                isinstance(reset_7d, int)
                and reset_7d - now_ms <= DASHBOARD_7D_RESET_REFRESH_THRESHOLD_MS
            ):
                due_background.append(
                    (
                        get_dashboard_row_refresh_priority(previous),
                        int(previous.get("_nextRefreshAtMs") or 0),
                        alias,
                    )
                )
                continue
            if (
                remaining_5h is not None
                and float(remaining_5h) < DASHBOARD_5H_LOW_REFRESH_THRESHOLD
            ):
                due_background.append(
                    (
                        get_dashboard_row_refresh_priority(previous),
                        int(previous.get("_nextRefreshAtMs") or 0),
                        alias,
                    )
                )
                continue
            next_refresh_at_ms = previous.get("_nextRefreshAtMs")
            if not isinstance(next_refresh_at_ms, int):
                next_refresh_at_ms = compute_dashboard_row_next_refresh_at(
                    previous,
                    is_current=False,
                    now_ms=now_ms,
                )
            if int(next_refresh_at_ms) > now_ms:
                continue
            due_background.append(
                (
                    get_dashboard_row_refresh_priority(previous),
                    int(next_refresh_at_ms),
                    alias,
                )
            )
        due_background.sort(key=lambda item: (item[0], item[1], item[2]))
        for _priority, _next_refresh_at_ms, alias in due_background[
            :DASHBOARD_MAX_BACKGROUND_REFRESHES_PER_CYCLE
        ]:
            scheduled_aliases.add(alias)

    scheduled_items = [
        (alias, raw_profile)
        for alias, raw_profile in account_items
        if alias in scheduled_aliases
    ]
    cached_items = [
        (alias, raw_profile)
        for alias, raw_profile in account_items
        if alias not in scheduled_aliases
    ]

    if len(scheduled_items) <= 1:
        for index, (alias, raw_profile) in enumerate(scheduled_items, start=1):
            if progress_fn:
                progress_fn(
                    get_account_display_name(alias, raw_profile),
                    index,
                    len(scheduled_items),
                )
            rows.append(
                build_dashboard_row_for_account(
                    alias,
                    raw_profile,
                    current_alias,
                    fetch_usage_fn,
                    fetch_catalog_fn,
                    previous=previous_rows_by_alias.get(alias),
                    on_profile_refreshed=record_refreshed_profile,
                    ignore_auth_block=False,
                )
            )
    else:
        worker_count = max(1, min(int(max_workers), len(scheduled_items)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    build_dashboard_row_for_account,
                    alias,
                    raw_profile,
                    current_alias,
                    fetch_usage_fn,
                    fetch_catalog_fn,
                    previous_rows_by_alias.get(alias),
                    record_refreshed_profile,
                    False,
                ): (alias, raw_profile)
                for alias, raw_profile in scheduled_items
            }
            completed = 0
            for future in as_completed(future_map):
                alias, raw_profile = future_map[future]
                completed += 1
                if progress_fn:
                    progress_fn(
                        get_account_display_name(alias, raw_profile),
                        completed,
                        len(scheduled_items),
                    )
                rows.append(future.result())

    for alias, raw_profile in cached_items:
        previous = previous_rows_by_alias.get(alias)
        if isinstance(previous, dict) and previous:
            rows.append(build_cached_row(alias, raw_profile, previous))
            continue
        rows.append(
            build_dashboard_row_for_account(
                alias,
                raw_profile,
                current_alias,
                fetch_usage_fn,
                fetch_catalog_fn,
                previous=None,
                on_profile_refreshed=record_refreshed_profile,
                ignore_auth_block=False,
            )
        )

    if refreshed_profiles and isinstance(accounts, dict):
        changed = False
        for alias, refreshed_profile in refreshed_profiles.items():
            raw_profile = accounts.get(alias)
            if not isinstance(raw_profile, dict):
                continue
            if merge_refreshed_profile(raw_profile, refreshed_profile):
                changed = True
        if changed:
            save_store(store, root)

    save_dashboard_snapshot_rows(rows, root)

    rows.sort(key=lambda item: (not bool(item["isCurrent"]), str(item["alias"])))
    return rows


def get_dashboard_rows_cached(
    state: DashboardState,
    root: Path = ROOT,
    build_rows_fn: Callable[..., list[JsonDict]] = build_dashboard_rows,
    force_refresh: bool = False,
) -> list[JsonDict]:
    if force_refresh or state.dirty:
        state.rows = build_rows_fn(root, previous_rows=state.rows)
        state.dirty = False
        state.last_refresh_at_ms = current_time_ms()
        state.last_refresh_error = None
    return state.rows


def refresh_dashboard_rows_from_store(
    state: DashboardState, root: Path = ROOT
) -> list[JsonDict]:
    store = load_store(root)
    accounts = store.get("accounts", {})
    current_alias = get_selected_alias(root)
    previous_source_rows = state.rows or load_dashboard_snapshot_rows(root)
    previous_rows = {
        str(row.get("alias", "")): row
        for row in previous_source_rows
        if isinstance(row, dict) and row.get("alias")
    }
    rows: list[JsonDict] = []
    for alias, raw_profile in accounts.items():
        if not isinstance(alias, str) or not isinstance(raw_profile, dict):
            continue
        previous = previous_rows.get(alias, {})
        profile = normalize_saved_profile(raw_profile)
        rows.append(
            {
                "alias": alias,
                "displayName": get_account_display_name(alias, raw_profile),
                "accountId": profile["accountId"] or "未知",
                "isCurrent": alias == current_alias,
                "plan": previous.get("plan", "未知"),
                "windows": previous.get("windows", []),
                "groups": previous.get("groups", []),
                "error": previous.get("error"),
                "warning": previous.get("warning"),
                "_authIssueStatus": previous.get("_authIssueStatus"),
                "_authIssueCount": previous.get("_authIssueCount", 0),
                "_authIssueFirstAtMs": previous.get("_authIssueFirstAtMs"),
                "_authBlockedUntilMs": previous.get("_authBlockedUntilMs"),
                "_authBlockedRefresh": previous.get("_authBlockedRefresh"),
                "_lastRefreshedAtMs": previous.get("_lastRefreshedAtMs"),
                "_nextRefreshAtMs": previous.get("_nextRefreshAtMs"),
                "_dailyRefreshAttemptDay": previous.get("_dailyRefreshAttemptDay"),
                "_dailyRefreshAttemptAtMs": previous.get("_dailyRefreshAttemptAtMs"),
                "_dailyRefreshSuccessDay": previous.get("_dailyRefreshSuccessDay"),
                "_refreshedThisCycle": False,
            }
        )
    rows.sort(key=lambda item: (not bool(item["isCurrent"]), str(item["alias"])))
    state.rows = rows
    state.dirty = False
    return rows


def refresh_dashboard_with_loading(
    state: DashboardState,
    root: Path = ROOT,
    build_rows_fn: Callable[..., list[JsonDict]] = build_dashboard_rows,
    status_factory: Callable[[str], Any] | None = None,
) -> list[JsonDict]:
    factory = status_factory or (
        lambda status_message: console.status(
            f"[bold cyan]{status_message}[/bold cyan]", spinner="dots"
        )
    )
    clear_screen()
    with factory("正在刷新首页数据...") as status:

        def progress(account_name: str, index: int, total: int) -> None:
            if hasattr(status, "update"):
                status.update(
                    f"[bold cyan]正在刷新第 {index}/{total} 个账号：{account_name}[/bold cyan]"
                )

        rows = build_rows_fn(root, progress_fn=progress, previous_rows=state.rows)
    state.rows = rows
    state.dirty = False
    state.last_refresh_at_ms = current_time_ms()
    state.last_refresh_error = None
    return rows


def refresh_dashboard_silently(
    state: DashboardState,
    root: Path = ROOT,
    build_rows_fn: Callable[..., list[JsonDict]] = build_dashboard_rows,
) -> list[JsonDict]:
    rows = build_rows_fn(root, previous_rows=state.rows)
    state.rows = rows
    state.dirty = False
    state.last_refresh_at_ms = current_time_ms()
    state.last_refresh_error = None
    return rows


def start_dashboard_refresh_worker(
    state: DashboardState,
    root: Path = ROOT,
    build_rows_fn: Callable[..., list[JsonDict]] = build_dashboard_rows,
    message: str = "加载中",
) -> None:
    if state.pending_refresh_thread is not None:
        return

    def worker() -> None:
        try:
            state.pending_refresh_rows = list(
                build_rows_fn(root, previous_rows=state.rows)
            )
            state.pending_refresh_error = None
        except Exception as exc:
            state.pending_refresh_rows = None
            state.pending_refresh_error = exc

    state.is_refreshing = True
    state.refresh_message = message
    state.refresh_frame_index = 0
    state.pending_refresh_rows = None
    state.pending_refresh_error = None
    state.pending_refresh_thread = threading.Thread(target=worker, daemon=True)
    state.pending_refresh_thread.start()


def tick_dashboard_refresh_worker(state: DashboardState) -> bool:
    thread = state.pending_refresh_thread
    if thread is None:
        return False
    state.refresh_frame_index = (state.refresh_frame_index + 1) % len(
        REFRESH_BAR_FRAMES
    )
    if thread.is_alive():
        return True
    thread.join()
    state.pending_refresh_thread = None
    state.is_refreshing = False
    if state.pending_refresh_error is not None:
        state.last_refresh_error = format_dashboard_error(state.pending_refresh_error)
        state.last_refresh_at_ms = current_time_ms()
        state.pending_refresh_error = None
        return True
    state.rows = list(state.pending_refresh_rows or [])
    state.pending_refresh_rows = None
    state.dirty = False
    state.last_refresh_at_ms = current_time_ms()
    state.last_refresh_error = None
    return True


def refresh_dashboard_in_place(
    state: DashboardState,
    root: Path,
    panel_text_fn: Callable[[], str],
    options: list[JsonDict],
    selected_index: int,
    hint: str = "",
    build_rows_fn: Callable[..., list[JsonDict]] = build_dashboard_rows,
) -> list[JsonDict]:
    result: dict[str, Any] = {"done": False, "rows": None, "error": None}

    def worker() -> None:
        try:
            result["rows"] = build_rows_fn(root, previous_rows=state.rows)
        except Exception as exc:
            result["error"] = exc
        finally:
            result["done"] = True

    state.is_refreshing = True
    state.refresh_message = "Loading"
    state.refresh_frame_index = 0
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    with Live(console=console, screen=True, auto_refresh=False) as live:
        while not result["done"]:
            state.refresh_frame_index = (state.refresh_frame_index + 1) % len(
                REFRESH_BAR_FRAMES
            )
            live.update(
                build_menu_screen(
                    panel_text_fn(),
                    options,
                    selected_index,
                    hint=hint,
                    panel_header_status=build_dashboard_panel_subtitle(state),
                    panel_footer_status=build_dashboard_panel_footer_status(state),
                ),
                refresh=True,
            )
            time.sleep(0.06)
        worker_thread.join()
    state.is_refreshing = False
    if result["error"] is not None:
        state.last_refresh_error = format_dashboard_error(result["error"])
        raise result["error"]
    rows = list(result["rows"] or [])
    state.rows = rows
    state.dirty = False
    state.last_refresh_at_ms = current_time_ms()
    state.last_refresh_error = None
    return rows


def render_dashboard(root: Path = ROOT) -> str:
    rows = build_dashboard_rows(root)
    current_display = get_selected_display_name(root)
    current_label = current_display or get_selected_alias(root) or "未选择"
    return render_dashboard_text(rows, current_label)


def cmd_dashboard() -> int:
    print(render_dashboard(ROOT))
    return 0


def render_overview_screen(rows: list[JsonDict], filter_key: str) -> str:
    filter_labels = {
        "all": "全部",
        "available": "可用",
        "unavailable": "不可用",
    }
    tabs = []
    for key in ["all", "available", "unavailable"]:
        label = filter_labels[key]
        if key == filter_key:
            tabs.append(f"[bold black on cyan] {label} [/]")
        else:
            tabs.append(f"[dim]{label}[/dim]")
    body = render_dashboard_text(
        filter_dashboard_rows(rows, filter_key), "账号总览", include_header=False
    )
    return "\n".join(
        [
            "[bold cyan]账号总览[/bold cyan]",
            " ".join(tabs),
            body,
        ]
    )


def show_panel_screen(content: str, title: str) -> None:
    _ = show_live_panel(Panel.fit(content, border_style="cyan", title=title))


def show_dashboard_overview_with_loading(
    load_rows_fn: Callable[[Path], list[JsonDict]] | None = None,
    run_with_loading_fn: Callable[
        [str, Callable[[], Any], Callable[[str], Any] | None], Any
    ] = run_with_loading,
    show_screen_fn: Callable[[str, str], None] | None = None,
    root: Path = ROOT,
) -> None:
    rows = run_with_loading_fn(
        "正在打开账号总览...",
        lambda: (load_rows_fn or build_dashboard_rows)(root),
        None,
    )
    if show_screen_fn is not None:
        show_screen_fn(render_overview_screen(rows, "all"), "账号总览")
        return
    filter_order = ["all", "available", "unavailable"]
    index = 0

    def render_current() -> Panel:
        return build_loading_panel(
            render_overview_screen(rows, filter_order[index]),
            None,
            None,
        )

    clear_screen()
    with Live(
        render_current(), console=console, screen=True, auto_refresh=False
    ) as live:
        while True:
            key = read_key()
            if key == "left":
                index = (index - 1) % len(filter_order)
                live.update(render_current(), refresh=True)
                continue
            if key == "right":
                index = (index + 1) % len(filter_order)
                live.update(render_current(), refresh=True)
                continue
            if key in {"escape", "backspace"}:
                return


def show_dashboard_overview() -> None:
    show_dashboard_overview_with_loading()


def show_dashboard_overview_in_place(
    state: DashboardState,
    panel_text_fn: Callable[[], str],
    options: list[JsonDict],
    selected_index: int,
    root: Path = ROOT,
    load_rows_fn: Callable[[Path], list[JsonDict]] = build_dashboard_rows,
) -> None:
    result: dict[str, Any] = {"done": False, "rows": None, "error": None}

    def worker() -> None:
        try:
            result["rows"] = load_rows_fn(root)
        except Exception as exc:
            result["error"] = exc
        finally:
            result["done"] = True

    state.is_refreshing = True
    state.refresh_message = "Loading"
    state.refresh_frame_index = 0
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    with Live(console=console, screen=True, auto_refresh=False) as live:
        while not result["done"]:
            state.refresh_frame_index = (state.refresh_frame_index + 1) % len(
                REFRESH_BAR_FRAMES
            )
            live.update(
                build_menu_screen(
                    panel_text_fn(),
                    options,
                    selected_index,
                    panel_header_status=build_dashboard_panel_subtitle(state),
                    panel_footer_status=build_dashboard_panel_footer_status(state),
                ),
                refresh=True,
            )
            time.sleep(0.06)
        worker_thread.join()
    state.is_refreshing = False
    if result["error"] is not None:
        state.last_refresh_error = format_dashboard_error(result["error"])
        raise result["error"]

    rows = list(result["rows"] or [])
    filter_order = ["all", "available", "unavailable"]
    index = 0

    def render_current() -> Panel:
        return build_loading_panel(
            render_overview_screen(rows, filter_order[index]),
            build_dashboard_panel_subtitle(state),
            build_dashboard_panel_footer_status(state),
        )

    with Live(
        render_current(), console=console, screen=True, auto_refresh=False
    ) as live:
        live.update(render_current(), refresh=True)
        while True:
            key = read_key_with_timeout(MENU_IDLE_TICK_MS)
            if key is None:
                state.monitor_frame_tick = (
                    state.monitor_frame_tick + 1
                ) % MONITOR_FRAME_STEP
                if state.monitor_frame_tick == 0:
                    state.monitor_frame_index = (state.monitor_frame_index + 1) % len(
                        MONITOR_FRAMES
                    )
                live.update(render_current(), refresh=True)
                continue
            if key == "left":
                index = (index - 1) % len(filter_order)
                live.update(render_current(), refresh=True)
                continue
            if key == "right":
                index = (index + 1) % len(filter_order)
                live.update(render_current(), refresh=True)
                continue
            if key in {"escape", "backspace"}:
                return


def cmd_save(alias: str) -> int:
    profile = extract_current_profile(ROOT)
    store = load_store(ROOT)
    store["accounts"][alias] = {
        **profile,
        "savedAt": now_iso(),
    }
    store["active"] = alias
    save_store(store, ROOT)

    print(f"已保存账号别名：{alias}")
    print(f"- 账号ID：{profile.get('accountId') or '未知'}")
    print(f"- refresh: {mask(profile.get('refresh', ''))}")
    print(f"- 存储文件：{root_store_file(ROOT)}")
    return 0


def cmd_add(
    alias: str | None = None,
    helper_login_fn: Callable[[], JsonDict] = run_openai_login_helper,
    upsert_profile_fn: Callable[
        [Path, JsonDict, str | None], str
    ] = upsert_account_profile,
) -> int:
    if alias is not None:
        saved_alias = add_account_via_login(ROOT, alias)
        print(f"已添加账号：{saved_alias}")
        print("- 登录完成，凭据已保存")
        return 0

    if login_helper_available():
        try:
            saved_alias = add_account_via_login_helper(
                ROOT, login_fn=helper_login_fn, upsert_profile_fn=upsert_profile_fn
            )
            print(f"已通过登录链接导入账号：{saved_alias}")
            print("- 浏览器登录完成后，回贴回调地址即可保存账号")
            return 0
        except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
            print(f"- 自动登录助手暂时不可用，已切换为手动回调登录：{exc}")

    saved_alias = add_account_via_manual_callback_fallback(
        ROOT,
        start_login_fn=cmd_login_session_payload,
        prompt_callback_fn=prompt_text,
        finish_login_fn=cmd_login_finish_payload,
        upsert_profile_fn=upsert_profile_fn,
    )
    print(f"已通过手动回调导入账号：{saved_alias}")
    print("- 你可以在浏览器完成登录后，把 localhost 回调地址贴回终端")
    return 0


def cmd_login_session_payload() -> JsonDict:
    return start_login_session(ROOT)


def cmd_login_finish_payload(callback_url: str) -> JsonDict:
    return complete_login_session(ROOT, callback_url)


def cmd_init(
    root: Path = ROOT,
    openclaw_config_path: Path | None = None,
    opencode_config_path: Path = OPENCODE_CONFIG_FILE,
    opencode_auth_path: Path = OPENCODE_AUTH_FILE,
) -> int:
    summary = initialize_environment(
        root=root,
        openclaw_config_path=openclaw_config_path,
        opencode_config_path=opencode_config_path,
        opencode_auth_path=opencode_auth_path,
    )
    print("初始化完成")
    if variant_requires_openclaw_login():
        print(f"- OpenClAW 根目录：{summary['root']}")
        print(f"- OpenClAW 配置：{summary['openclaw_config_path']}")
        print(f"- 已检查 agent 模型文件数：{summary['agent_count']}")
        print(f"- 已确保 OpenClAW 模型：{TARGET_OPENCLAW_MODEL_ID}")
    if variant_requires_opencode_config():
        print(f"- OpenCode 配置：{summary['opencode_config_path']}")
        print(f"- OpenCode 凭据路径：{summary['opencode_auth_path']}")
        print(f"- 已确保 OpenCode 模型：{TARGET_OPENCODE_MODEL_KEY}")
    return 0


def cmd_login_start() -> int:
    session = start_login_session(ROOT)
    print("请在浏览器中打开下面这个链接完成登录：")
    print(session["url"])
    print("- 登录完成后，把浏览器最后跳转到的 localhost 回调地址完整贴回来")
    return 0


def cmd_login_finish(callback_url: str) -> int:
    profile = complete_login_session(ROOT, callback_url)
    alias = upsert_account_profile(ROOT, profile, source="manual-oauth-callback")
    print(f"已完成登录并保存账号：{alias}")
    print(f"- 账号ID：{profile.get('accountId') or '未知'}")
    print(f"- 邮箱：{profile.get('email') or '未知'}")
    return 0


def cmd_import() -> int:
    saved_alias = import_current_openclaw_login(ROOT)
    print(f"已导入当前登录态：{saved_alias}")
    print("- 你可以先用官方登录，然后回到这里执行导入")
    return 0


def cmd_list() -> int:
    store = load_store(ROOT)
    active = get_selected_alias(ROOT)
    accounts = store.get("accounts", {})
    if not accounts:
        print("还没有保存账号。")
        return 0
    print("已保存账号：")
    for alias, profile in accounts.items():
        mark = "当前" if alias == active else "待命"
        display_name = get_account_display_name(alias, profile)
        print(
            f"[{mark}] {display_name} | 账号ID={profile.get('accountId') or '未知'} | expires={profile.get('expires', 0)}"
        )
    return 0


def cmd_rename(alias: str, display_name: str) -> int:
    set_account_display_name(ROOT, alias, display_name)
    print(f"已更新账号名称：{alias}")
    print(f"- 新名称：{display_name}")
    return 0


def apply_profile_to_agent(adir: Path, profile: JsonDict) -> list[Path]:
    backups: list[Path] = []

    ap_path = adir / "auth-profiles.json"
    ap_data = read_json(ap_path)
    ap_data.setdefault("version", 1)
    ap_data.setdefault("profiles", {})
    ap_data["profiles"][PROFILE_KEY] = {
        "type": "oauth",
        "provider": PROVIDER_KEY,
        "access": profile.get("access", ""),
        "refresh": profile.get("refresh", ""),
        "expires": profile.get("expires", 0),
        "accountId": profile.get("accountId", ""),
    }
    ap_data.setdefault("lastGood", {})
    ap_data["lastGood"][PROVIDER_KEY] = PROFILE_KEY
    ap_data.setdefault("usageStats", {})
    ap_data["usageStats"].setdefault(PROFILE_KEY, {"lastUsed": 0, "errorCount": 0})
    if ap_path.exists():
        backups.append(backup(ap_path))
    write_json(ap_path, ap_data)

    auth_path = adir / "auth.json"
    auth_data = read_json(auth_path)
    auth_data[PROVIDER_KEY] = {
        "type": "oauth",
        "access": profile.get("access", ""),
        "refresh": profile.get("refresh", ""),
        "expires": profile.get("expires", 0),
        "accountId": profile.get("accountId", ""),
    }
    if auth_path.exists():
        backups.append(backup(auth_path))
    write_json(auth_path, auth_data)

    return backups


def apply_profile_to_opencode(auth_path: Path, profile: JsonDict) -> list[Path]:
    backups: list[Path] = []
    auth_data = read_json(auth_path)
    auth_data["openai"] = {
        "type": "oauth",
        "access": profile.get("access", ""),
        "refresh": profile.get("refresh", ""),
        "expires": profile.get("expires", 0),
        "accountId": profile.get("accountId", ""),
    }
    if auth_path.exists():
        backups.append(backup(auth_path))
    write_json(auth_path, auth_data)
    return backups


def switch_alias(
    root: Path,
    alias: str,
    opencode_auth_path: Path | None = None,
    audit_event: JsonDict | None = None,
) -> int:
    store = load_store(root)
    accounts = store.get("accounts", {})
    detected_from_alias = detect_current_alias(root)
    store_active_alias = (
        store.get("active") if isinstance(store.get("active"), str) else None
    )
    from_alias = detected_from_alias or store_active_alias
    from_profile = store.get("accounts", {}).get(from_alias or "", {})
    profile = accounts.get(alias)
    if not isinstance(profile, dict):
        raise ValueError(f"未找到账号别名：{alias}")
    if profile.get("type") != "oauth" or not profile.get("refresh"):
        raise ValueError(f"账号凭据无效：{alias}")

    dirs = agent_dirs(root) if variant_is_openclaw() else []
    if variant_is_openclaw() and not dirs:
        raise ValueError("没有找到 ~/.openclaw/agents 下的 agent 目录")

    backup_paths: list[Path] = []
    target_opencode_auth = opencode_auth_path or OPENCODE_AUTH_FILE
    payload = dict(audit_event or {})
    payload.setdefault("action", "account-switch")
    payload.setdefault("mode", "direct")
    payload["fromAlias"] = str(from_alias or "")
    payload["fromDetectedAlias"] = str(detected_from_alias or "")
    payload["fromStoreActiveAlias"] = str(store_active_alias or "")
    payload["fromDisplayName"] = get_account_display_name(
        str(from_alias or ""), from_profile if isinstance(from_profile, dict) else {}
    )
    payload["fromAccountId"] = str(
        (from_profile if isinstance(from_profile, dict) else {}).get("accountId") or ""
    )
    payload["toAlias"] = alias
    payload["toDisplayName"] = get_account_display_name(alias, profile)
    payload["toAccountId"] = str(profile.get("accountId") or "")
    try:
        if variant_is_openclaw():
            for adir in dirs:
                backup_paths.extend(apply_profile_to_agent(adir, profile))
        if variant_is_opencode():
            backup_paths.extend(
                apply_profile_to_opencode(target_opencode_auth, profile)
            )
        store["active"] = alias
        save_store(store, root)
        payload["status"] = "success"
        payload["backupPaths"] = [str(path) for path in backup_paths]
        write_switch_audit_event(payload, root)
    except Exception as exc:
        payload["status"] = "failed"
        payload["error"] = str(exc)
        payload["backupPaths"] = [str(path) for path in backup_paths]
        write_switch_audit_event(payload, root)
        raise
    return len(dirs)


def cmd_switch(alias: str) -> int:
    store = load_store(ROOT)
    profile = store.get("accounts", {}).get(alias)
    if not isinstance(profile, dict):
        raise ValueError(f"未找到账号别名：{alias}")
    if profile.get("type") != "oauth" or not profile.get("refresh"):
        raise ValueError(f"账号凭据无效：{alias}")
    if variant_is_openclaw():
        dirs = agent_dirs(ROOT)
        if not dirs:
            raise ValueError("没有找到 ~/.openclaw/agents 下的 agent 目录")
    changed = switch_alias(
        ROOT,
        alias,
        audit_event={
            "action": "account-switch",
            "mode": "manual",
            "reasonCode": "manual-command",
        },
    )

    print(f"已切换到账号：{alias}")
    if variant_is_openclaw():
        print(f"- 已更新 agent 目录数：{changed}")
    if variant_is_opencode():
        print(f"- 已同步 OpenCode 凭据：{OPENCODE_AUTH_FILE}")
    print(f"- 已记录切号日志：{switch_audit_log_file(ROOT)}")
    print("- 一般无需重启；如果当前会话仍报 401，可再切一次账号或重开会话")
    return 0


def cmd_current() -> int:
    alias = get_selected_alias(ROOT)
    if not alias:
        print("当前还没有已添加的账号。")
        return 0
    store = load_store(ROOT)
    profile = normalize_saved_profile(store.get("accounts", {}).get(alias, {}))
    print("脚本当前选中的账号：")
    print(f"- 显示名称：{get_account_display_name(alias, profile)}")
    print(f"- 账号ID：{profile.get('accountId') or '未知'}")
    print(f"- refresh: {mask(profile.get('refresh', ''))}")
    print(f"- expires: {profile.get('expires', 0)}")
    return 0


def cmd_remove(alias: str) -> int:
    store = load_store(ROOT)
    accounts = store.get("accounts", {})
    if alias not in accounts:
        raise ValueError(f"未找到账号别名：{alias}")
    del accounts[alias]
    if store.get("active") == alias:
        store["active"] = None
    save_store(store, ROOT)
    print(f"已删除账号：{alias}")
    return 0


def cmd_usage() -> int:
    profile = extract_current_profile(ROOT)
    alias = detect_current_alias(ROOT)
    store = load_store(ROOT)
    display_name = (
        get_account_display_name(alias, store.get("accounts", {}).get(alias, {}))
        if alias
        else "未保存"
    )
    usage = fetch_codex_usage(profile)
    print("当前 openai-codex 额度：")
    print(f"- 显示名称：{display_name}")
    print(f"- 账号ID：{profile.get('accountId') or '未知'}")
    print(f"- 套餐：{usage.get('plan') or '未知'}")
    for window in usage.get("windows", []):
        remaining = max(0.0, 100.0 - float(window["usedPercent"]))
        print(
            f"- {window['label']}：已用={window['usedPercent']:.1f}% 剩余={remaining:.1f}% 重置={format_reset_at(window.get('resetAt'))}"
        )
    return 0


def cmd_show_logs(limit: int = 20) -> int:
    return cmd_logs(limit=limit, root=ROOT)


def run_menu_choice(
    choice: str,
    prompt_input: Callable[[str], str] = input,
    import_fn: Callable[[], int] = cmd_import,
    add_fn: Callable[[], int] = lambda: cmd_add(None),
    save_fn: Callable[[str], int] = cmd_save,
    rename_fn: Callable[[str, str], int] = cmd_rename,
    list_fn: Callable[[], int] = cmd_list,
    switch_fn: Callable[[str], int] = cmd_switch,
    remove_fn: Callable[[str], int] = cmd_remove,
    current_fn: Callable[[], int] = cmd_current,
    usage_fn: Callable[[], int] = cmd_usage,
    dashboard_fn: Callable[[], int] = cmd_dashboard,
) -> int:
    if choice == "1":
        return import_fn()
    if choice == "2":
        return add_fn()
    if choice == "3":
        return switch_fn(prompt_input("请输入要切换的账号别名：").strip())
    if choice == "4":
        return remove_fn(prompt_input("请输入要删除的账号别名：").strip())
    if choice == "5":
        return current_fn()
    if choice == "6":
        return usage_fn()
    if choice == "7":
        return list_fn()
    if choice == "8":
        return save_fn(prompt_input("请输入保存当前登录的账号别名：").strip())
    if choice == "9":
        return dashboard_fn()
    if choice == "10":
        alias = prompt_input("请输入要修改名称的账号别名：").strip()
        display_name = prompt_input("请输入新的显示名称：").strip()
        return rename_fn(alias, display_name)
    if choice == "0":
        return 0
    raise ValueError("Invalid menu choice")


def cmd_menu() -> int:
    if not ensure_environment_ready_for_menu():
        return 1
    dashboard_state = DashboardState()
    refresh_dashboard_rows_from_store(dashboard_state, ROOT)

    def build_home_text() -> str:
        rows = get_dashboard_rows_cached(dashboard_state, ROOT)
        current_display = get_selected_display_name(ROOT)
        current_label = current_display or get_selected_alias(ROOT) or "未选择"
        return render_home_dashboard_text(rows, current_label)

    def auto_refresh_dashboard() -> bool:
        dashboard_state.monitor_frame_tick = (
            dashboard_state.monitor_frame_tick + 1
        ) % MONITOR_FRAME_STEP
        if dashboard_state.monitor_frame_tick == 0:
            dashboard_state.monitor_frame_index = (
                dashboard_state.monitor_frame_index + 1
            ) % len(MONITOR_FRAMES)
        had_pending_refresh = dashboard_state.pending_refresh_thread is not None
        if tick_dashboard_refresh_worker(dashboard_state):
            if (
                had_pending_refresh
                and dashboard_state.pending_refresh_thread is None
                and not dashboard_state.is_refreshing
                and dashboard_state.last_refresh_error is None
            ):
                apply_auto_switch_if_needed(
                    dashboard_state,
                    current_alias=get_selected_alias(ROOT),
                    root=ROOT,
                )
            return True
        if not should_auto_refresh_dashboard(dashboard_state):
            return True
        start_dashboard_refresh_worker(dashboard_state, ROOT, message="Loading")
        return True

    while True:
        options = build_main_menu_options()
        selected = choose_from_menu(
            build_home_text,
            options,
            idle_timeout_ms=MENU_IDLE_TICK_MS,
            idle_action=auto_refresh_dashboard,
            panel_header_status=lambda: build_dashboard_panel_subtitle(dashboard_state),
            panel_footer_status=lambda: build_dashboard_panel_footer_status(
                dashboard_state
            ),
        )
        if selected is None:
            return 0

        action = selected["key"]
        try:
            if action == "add":
                run_action_with_status(lambda: cmd_add(None), "账号已添加")
                refresh_dashboard_rows_from_store(dashboard_state, ROOT)
                continue
            if action == "switch":
                store = load_store(ROOT)
                aliases = list(store.get("accounts", {}).keys())
                if not aliases:
                    show_status_screen("还没有可切换的账号")
                    continue
                picked = choose_from_menu(
                    build_account_picker_text(
                        "切换账号", "选择一个账号并立即切换为当前账号", len(aliases)
                    ),
                    build_account_choice_options(
                        store.get("accounts", {}), get_selected_alias(ROOT)
                    ),
                )
                if picked:
                    picked_key = str(picked["key"])
                    run_action_with_status(
                        lambda picked_key=picked_key: cmd_switch(picked_key),
                        f"已切换到 {picked_key}",
                    )
                    refresh_dashboard_rows_from_store(dashboard_state, ROOT)
                continue
            if action == "overview":
                selected_index = next(
                    (
                        idx
                        for idx, item in enumerate(options)
                        if str(item.get("key") or "") == "overview"
                    ),
                    0,
                )
                show_dashboard_overview_in_place(
                    dashboard_state,
                    build_home_text,
                    options,
                    selected_index,
                    ROOT,
                )
                continue
            if action == "rename":
                store = load_store(ROOT)
                accounts = store.get("accounts", {})
                aliases = list(accounts.keys())
                if not aliases:
                    show_status_screen("还没有可修改名称的账号")
                    continue
                picked = choose_from_menu(
                    build_account_picker_text(
                        "修改名称", "先选择账号，再输入新的显示名称", len(aliases)
                    ),
                    build_account_choice_options(accounts, get_selected_alias(ROOT)),
                )
                if picked:
                    picked_key = str(picked["key"])
                    new_name = prompt_text("请输入新的显示名称")
                    if new_name:
                        run_action_with_status(
                            lambda picked_key=picked_key, new_name=new_name: cmd_rename(
                                picked_key, new_name
                            ),
                            f"已更新 {picked_key} 的名称",
                        )
                        refresh_dashboard_rows_from_store(dashboard_state, ROOT)
                continue
            if action == "remove":
                store = load_store(ROOT)
                aliases = list(store.get("accounts", {}).keys())
                if not aliases:
                    show_status_screen("还没有可删除的账号")
                    continue
                picked = choose_from_menu(
                    build_account_picker_text(
                        "删除账号", "选择一个账号并从本地列表中移除", len(aliases)
                    ),
                    build_account_choice_options(
                        store.get("accounts", {}), get_selected_alias(ROOT)
                    ),
                )
                if picked:
                    picked_key = str(picked["key"])
                    run_action_with_status(
                        lambda picked_key=picked_key: cmd_remove(picked_key),
                        f"已删除 {picked_key}",
                    )
                    refresh_dashboard_rows_from_store(dashboard_state, ROOT)
                continue
            if action == "current":
                run_action_with_status(cmd_current, "当前账号")
                continue
            if action == "usage":
                run_action_with_status(cmd_usage, "当前额度")
                continue
            if action == "list":
                run_action_with_status(cmd_list, "账号列表")
                continue
            if action == "save":
                alias = prompt_text("请输入保存当前登录的账号别名")
                if alias:
                    saved_alias = alias
                    run_action_with_status(
                        lambda saved_alias=saved_alias: cmd_save(saved_alias),
                        "当前登录已保存为账号",
                    )
                    refresh_dashboard_rows_from_store(dashboard_state, ROOT)
                continue
            if action == "refresh":
                selected_index = next(
                    (
                        idx
                        for idx, item in enumerate(options)
                        if str(item.get("key") or "") == "refresh"
                    ),
                    0,
                )
                refresh_dashboard_in_place(
                    dashboard_state,
                    ROOT,
                    build_home_text,
                    options,
                    selected_index,
                    build_rows_fn=lambda root,
                    progress_fn=None,
                    previous_rows=None: build_dashboard_rows(
                        root,
                        progress_fn=progress_fn,
                        previous_rows=previous_rows,
                        force_full_refresh=True,
                    ),
                )
                continue
            if action == "exit":
                return 0
        except Exception as exc:
            show_status_screen(f"操作失败：{exc}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpenAI Hub account switcher")
    sub = p.add_subparsers(dest="cmd")

    p_save = sub.add_parser("save", help="save current oauth token as alias")
    p_save.add_argument("alias")

    p_add = sub.add_parser("add", help="login in browser and save oauth alias")
    p_add.add_argument("alias", nargs="?")

    p_init = sub.add_parser("init", help="initialize local OpenClAW/OpenCode config")
    p_init.add_argument("--root", type=Path, default=ROOT)
    p_init.add_argument("--openclaw-config", type=Path, default=None)
    p_init.add_argument("--opencode-config", type=Path, default=OPENCODE_CONFIG_FILE)
    p_init.add_argument("--opencode-auth", type=Path, default=OPENCODE_AUTH_FILE)

    sub.add_parser("list", help="list saved aliases")

    p_switch = sub.add_parser("switch", help="switch to alias")
    p_switch.add_argument("alias")

    p_remove = sub.add_parser("remove", help="remove alias")
    p_remove.add_argument("alias")

    p_rename = sub.add_parser("rename", help="rename saved account display name")
    p_rename.add_argument("alias")
    p_rename.add_argument("display_name")

    sub.add_parser("current", help="show current oauth summary")
    sub.add_parser("usage", help="show current codex usage windows")
    p_logs = sub.add_parser("logs", help="show recent account switch audit logs")
    p_logs.add_argument("--limit", type=int, default=20)
    sub.add_parser("dashboard", help="show account dashboard")
    sub.add_parser("menu", help="interactive menu for switching")
    sub.add_parser("login-start", help="start manual oauth login session")
    p_login_finish = sub.add_parser(
        "login-finish", help="finish manual oauth login with callback url"
    )
    p_login_finish.add_argument("callback_url")
    return p


def main() -> int:
    args = parser().parse_args()
    set_default_console_size()
    cmd = str(getattr(args, "cmd", "") or "menu")
    try:
        with hidden_cursor():
            if cmd == "save":
                return cmd_save(args.alias)
            if cmd == "add":
                return cmd_add(args.alias)
            if cmd == "init":
                return cmd_init(
                    args.root,
                    args.openclaw_config,
                    args.opencode_config,
                    args.opencode_auth,
                )
            if cmd == "list":
                return cmd_list()
            if cmd == "switch":
                return cmd_switch(args.alias)
            if cmd == "remove":
                return cmd_remove(args.alias)
            if cmd == "rename":
                return cmd_rename(args.alias, args.display_name)
            if cmd == "current":
                return cmd_current()
            if cmd == "usage":
                return cmd_usage()
            if cmd == "logs":
                return cmd_show_logs(args.limit)
            if cmd == "dashboard":
                return cmd_dashboard()
            if cmd == "menu":
                return cmd_menu()
            if cmd == "login-start":
                return cmd_login_start()
            if cmd == "login-finish":
                return cmd_login_finish(args.callback_url)
            raise ValueError("Unknown command")
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
