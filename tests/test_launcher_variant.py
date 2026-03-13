import importlib.util
from contextlib import contextmanager
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

    def test_switcher_menu_prompts_variant_when_env_missing(self) -> None:
        original_argv = list(sys.argv)
        original_env = os.environ.get("GT_VARIANT")
        sys.modules.pop("openclaw_oauth_switcher", None)

        @contextmanager
        def no_cursor():
            yield

        try:
            os.environ.pop("GT_VARIANT", None)
            switcher = load_module("openclaw_oauth_switcher", SWITCHER_PATH)
            seen_variants: list[str] = []

            setattr(switcher, "choose_from_menu", lambda **_kwargs: {"key": "openclaw"})
            setattr(switcher, "set_default_console_size", lambda: None)
            setattr(switcher, "hidden_cursor", no_cursor)
            setattr(
                switcher,
                "cmd_menu",
                lambda: seen_variants.append(switcher.get_app_variant()) or 0,
            )

            sys.argv = [str(SWITCHER_PATH), "menu"]
            exit_code = switcher.main()
        finally:
            sys.argv = original_argv
            if original_env is None:
                os.environ.pop("GT_VARIANT", None)
            else:
                os.environ["GT_VARIANT"] = original_env
            sys.modules.pop("openclaw_oauth_switcher", None)

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_variants, ["openclaw"])

    def test_cmd_menu_starts_full_refresh_worker_after_loading_snapshot(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher", None)
        switcher = load_module("openclaw_oauth_switcher", SWITCHER_PATH)

        calls: list[tuple[str, dict[str, object] | Path]] = []

        def fake_refresh(state, root):
            state.rows = [{"alias": "cached", "isCurrent": True}]
            state.dirty = False
            calls.append(("snapshot", root))
            return state.rows

        def fake_start_worker(state, root, build_rows_fn=None, message=""):
            rows = []
            if callable(build_rows_fn):
                rows = build_rows_fn(root, previous_rows=list(state.rows))
            calls.append(("worker", {"root": root, "message": message, "rows": rows}))

        setattr(switcher, "ensure_environment_ready_for_menu", lambda: True)
        setattr(switcher, "refresh_dashboard_rows_from_store", fake_refresh)
        setattr(switcher, "start_dashboard_refresh_worker", fake_start_worker)
        setattr(
            switcher,
            "build_dashboard_rows",
            lambda root,
            progress_fn=None,
            previous_rows=None,
            force_full_refresh=False: [
                {
                    "root": root,
                    "force_full_refresh": force_full_refresh,
                    "previous_rows": list(previous_rows or []),
                }
            ],
        )
        setattr(switcher, "choose_from_menu", lambda *args, **kwargs: None)

        exit_code = switcher.cmd_menu()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0][0], "snapshot")
        self.assertEqual(calls[1][0], "worker")
        worker_payload = calls[1][1]
        if not isinstance(worker_payload, dict):
            self.fail("worker payload should be a dict")
        self.assertEqual(worker_payload["message"], "Loading")
        rows = worker_payload["rows"]
        if not isinstance(rows, list) or not rows:
            self.fail("worker rows should be a non-empty list")
        first_row = rows[0]
        if not isinstance(first_row, dict):
            self.fail("worker row should be a dict")
        self.assertTrue(first_row["force_full_refresh"])
        self.assertEqual(
            first_row["previous_rows"],
            [{"alias": "cached", "isCurrent": True}],
        )

    def test_cmd_menu_starts_background_api_gateway_before_rendering_menu(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher", None)
        switcher = load_module("openclaw_oauth_switcher", SWITCHER_PATH)

        calls: list[tuple[str, object]] = []

        setattr(switcher, "ensure_environment_ready_for_menu", lambda: True)
        setattr(
            switcher,
            "refresh_dashboard_rows_from_store",
            lambda state, root: calls.append(("snapshot", root)) or [],
        )
        setattr(
            switcher,
            "start_initial_dashboard_full_refresh",
            lambda state, root: calls.append(("dashboard", root)),
        )
        setattr(
            switcher,
            "ensure_background_api_gateway_running",
            lambda root: calls.append(("api", root))
            or {
                "url": "http://127.0.0.1:8321",
                "apiKey": "demo-key",
                "stateFile": "demo-state.json",
                "started": True,
            },
        )
        setattr(switcher, "choose_from_menu", lambda *args, **kwargs: None)

        exit_code = switcher.cmd_menu()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0][0], "snapshot")
        self.assertEqual(calls[1][0], "dashboard")
        self.assertEqual(calls[2][0], "api")

    def test_menu_api_config_allows_updating_api_key(self) -> None:
        sys.modules.pop("openclaw_oauth_switcher_api_menu_update", None)
        switcher = load_module("openclaw_oauth_switcher_api_menu_update", SWITCHER_PATH)

        shown: list[tuple[str, str | None]] = []

        setattr(
            switcher,
            "ensure_background_api_gateway_running",
            lambda root: {
                "url": "http://127.0.0.1:8321",
                "apiKey": "old-key",
                "stateFile": "state.json",
                "started": False,
            },
        )
        setattr(
            switcher,
            "choose_from_menu",
            lambda *args, **kwargs: {"key": "set-key"},
        )
        setattr(switcher, "prompt_text", lambda _prompt: "new-key")
        setattr(
            switcher,
            "cmd_api_set_key",
            lambda api_key: shown.append(("updated", api_key)) or 0,
        )
        setattr(
            switcher,
            "show_status_screen",
            lambda message, detail=None: shown.append((message, detail)),
        )

        exit_code = switcher.show_api_config_menu()

        self.assertEqual(exit_code, 0)
        self.assertIn(("updated", "new-key"), shown)


if __name__ == "__main__":
    unittest.main()
