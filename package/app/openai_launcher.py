#!/usr/bin/env python3
import importlib
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
APP_RELEASE_VERSION = "1.1.15"
APP_COMMAND_NAME = "openaihub"
APP_SHORT_COMMAND = "OAH"


def load_switcher_module():
    if __package__:
        return importlib.import_module(f"{__package__}.openclaw_oauth_switcher")
    return importlib.import_module("openclaw_oauth_switcher")


def choose_variant() -> str:
    switcher = load_switcher_module()
    title = "请选择启动模式"
    options = [
        {
            "key": "full",
            "label": "综合模式",
            "description": "检查 OpenClAW + OpenCode，切号时两边一起切",
        },
        {
            "key": "opencode",
            "label": "OpenCode 模式",
            "description": "检查 OpenCode，登录可走内置链路，切号时只改 OpenCode",
        },
        {
            "key": "openclaw",
            "label": "OpenClAW 模式",
            "description": "只检查 OpenClAW，切号时只改 OpenClAW",
        },
    ]
    selected = switcher.choose_from_menu(
        title=title,
        options=options,
        hint="先选择运行模式，再进入初始化与主菜单；Esc 可直接退出",
        panel_header_status="1.1 启动器",
        panel_footer_status="模式不同，检查范围和切号范围也不同",
    )
    if not selected:
        raise KeyboardInterrupt
    switcher.hide_cursor()
    return str(selected.get("key") or "full")


def print_help() -> None:
    print(f"OpenAI Hub {APP_RELEASE_VERSION}")
    print()
    print("Usage:")
    print(f"  {APP_COMMAND_NAME}           Start mode picker and open menu")
    print(f"  {APP_COMMAND_NAME} --help    Show this help")
    print(f"  {APP_COMMAND_NAME} --version Show version")
    print(f"  {APP_SHORT_COMMAND}          Alias of {APP_COMMAND_NAME}")
    print()
    print("Modes:")
    print("  full       Check OpenClAW + OpenCode, switch both")
    print("  opencode   Check OpenClAW + OpenCode, switch OpenCode only")
    print("  openclaw   Check OpenClAW only, switch OpenClAW only")


def print_unknown_args(args: list[str]) -> int:
    joined = " ".join(args)
    print(f"Unknown arguments: {joined}")
    print(f"Run `{APP_COMMAND_NAME} --help` for usage.")
    return 2


def main() -> int:
    args = sys.argv[1:]
    debug_flag = os.environ.get("OPENAIHUB_DEBUG_ARGS", "").strip()
    if debug_flag:
        debug_path = Path(tempfile.gettempdir()) / "openaihub-argv.txt"
        debug_path.write_text(repr(sys.argv), encoding="utf-8")
    if any(arg in {"--version", "-V", "version"} for arg in args):
        print(f"OpenAI Hub {APP_RELEASE_VERSION}")
        return 0
    if any(arg in {"--help", "-h", "help"} for arg in args):
        print_help()
        return 0
    if args:
        return print_unknown_args(args)
    try:
        switcher = load_switcher_module()
        variant = choose_variant()
    except KeyboardInterrupt:
        return 0
    env = os.environ.copy()
    env["GT_VARIANT"] = variant
    os.environ.update(env)
    if hasattr(switcher, "set_app_variant"):
        switcher.set_app_variant(variant)
    old_argv = list(sys.argv)
    try:
        sys.argv = [old_argv[0], "menu"]
        return int(switcher.main())
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
