import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "package"
    / "app"
    / "openclaw_oauth_switcher.py"
)
SPEC = importlib.util.spec_from_file_location(
    "openclaw_oauth_switcher_init_gate", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_with_loading_stub(
    _message: str,
    work_fn,
    _status_factory=None,
    finish_callback=None,
):
    summary = work_fn(progress_callback=None)
    if finish_callback is not None:
        finish_callback(object(), summary)
    return summary


class InitGatekeepingTests(unittest.TestCase):
    def test_full_mode_blocks_menu_when_openclaw_switch_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (root / "openclaw.json").write_text(
                '{"models":{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "models.json").write_text(
                '{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "auth.json").write_text("{}\n", encoding="utf-8")
            (agents_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{},"lastGood":{},"usageStats":{}}\n',
                encoding="utf-8",
            )
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            opencode_config.write_text(
                '{"provider":{"openai":{"models":{"gpt-5.4":{}}}}}\n',
                encoding="utf-8",
            )
            opencode_auth.write_text("{}\n", encoding="utf-8")
            MODULE.set_init_status(root, completed=True, verified=True)
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    initialize_fn=lambda **kwargs: MODULE.initialize_environment(
                        openclaw_program_probe_fn=lambda: True,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        switch_target_probe_fn=lambda *_args,
                        **_kwargs: MODULE.build_init_failure(
                            "openclaw-switch-target-unavailable",
                            agents_dir / "auth.json",
                        ),
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: True,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        switch_target_probe_fn=lambda *_args,
                        **_kwargs: MODULE.build_init_failure(
                            "openclaw-switch-target-unavailable",
                            agents_dir / "auth.json",
                        ),
                        **kwargs,
                    ),
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertIn("OpenClAW 切换目标文件", errors[-1][1] or "")

    def test_opencode_mode_blocks_menu_when_opencode_switch_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            root.mkdir(parents=True, exist_ok=True)
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            MODULE.write_json(root / "openai-hub-state.json", {})
            opencode_config.write_text(
                '{"provider":{"openai":{"models":{"gpt-5.4":{}}}}}\n',
                encoding="utf-8",
            )
            opencode_auth.write_text("{}\n", encoding="utf-8")
            MODULE.set_init_status(root, completed=True, verified=True)
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "opencode")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    initialize_fn=lambda **kwargs: MODULE.initialize_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        switch_target_probe_fn=lambda *_args,
                        **_kwargs: MODULE.build_init_failure(
                            "opencode-switch-target-unavailable",
                            opencode_auth,
                        ),
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        switch_target_probe_fn=lambda *_args,
                        **_kwargs: MODULE.build_init_failure(
                            "opencode-switch-target-unavailable",
                            opencode_auth,
                        ),
                        **kwargs,
                    ),
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertIn("OpenCode 切换目标文件", errors[-1][1] or "")

    def test_opencode_mode_allows_missing_local_openclaw_program(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            root.mkdir(parents=True, exist_ok=True)
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            MODULE.write_json(root / "openai-hub-state.json", {})
            opencode_config.write_text(
                '{"provider":{"openai":{"models":{"gpt-5.4":{}}}}}\n',
                encoding="utf-8",
            )
            opencode_auth.write_text("{}\n", encoding="utf-8")
            MODULE.set_init_status(root, completed=True, verified=True)

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "opencode")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    initialize_fn=lambda **kwargs: MODULE.initialize_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda *_args, **_kwargs: None,
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertTrue(ready)

    def test_full_mode_blocks_menu_when_openclaw_program_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (root / "openclaw.json").write_text(
                '{"models":{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "models.json").write_text(
                '{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "auth.json").write_text("{}\n", encoding="utf-8")
            (agents_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{},"lastGood":{},"usageStats":{}}\n',
                encoding="utf-8",
            )
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            opencode_config.write_text(
                '{"provider":{"openai":{"models":{"gpt-5.4":{}}}}}\n',
                encoding="utf-8",
            )
            opencode_auth.write_text("{}\n", encoding="utf-8")
            MODULE.set_init_status(root, completed=True, verified=True)
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    initialize_fn=lambda **kwargs: MODULE.initialize_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: False,
                        opencode_program_probe_fn=lambda: True,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertIn("OpenClAW 程序", errors[-1][1] or "")

    def test_full_mode_blocks_menu_when_opencode_program_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (root / "openclaw.json").write_text(
                '{"models":{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "models.json").write_text(
                '{"providers":{"openai-codex":{"models":[{"id":"gpt-5.4-codex"}]}}}\n',
                encoding="utf-8",
            )
            (agents_dir / "auth.json").write_text("{}\n", encoding="utf-8")
            (agents_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{},"lastGood":{},"usageStats":{}}\n',
                encoding="utf-8",
            )
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            opencode_config.write_text(
                '{"provider":{"openai":{"models":{"gpt-5.4":{}}}}}\n',
                encoding="utf-8",
            )
            opencode_auth.write_text("{}\n", encoding="utf-8")
            MODULE.set_init_status(root, completed=True, verified=True)
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    initialize_fn=lambda **kwargs: MODULE.initialize_environment(
                        openclaw_program_probe_fn=lambda: True,
                        opencode_program_probe_fn=lambda: False,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: True,
                        opencode_program_probe_fn=lambda: False,
                        openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                        **kwargs,
                    ),
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertIn("OpenCode 程序", errors[-1][1] or "")

    def test_full_mode_blocks_menu_when_openclaw_root_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "missing-openclaw-root"
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertEqual(errors[-1][0], "初始化失败")
        self.assertIn("OpenClAW 根目录", errors[-1][1] or "")
        self.assertIn(str(root), errors[-1][1] or "")

    def test_opencode_mode_blocks_menu_when_opencode_state_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "models.json").write_text("{}\n", encoding="utf-8")
            (root / "openclaw.json").write_text("{}\n", encoding="utf-8")
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            missing_state_auth = base / "missing-opencode-state" / "auth.json"
            errors: list[tuple[str, str | None]] = []

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "opencode")

                ready = MODULE.ensure_environment_ready_for_menu(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=missing_state_auth,
                    run_with_loading_fn=run_with_loading_stub,
                    show_error_fn=lambda message, detail=None: errors.append(
                        (message, detail)
                    ),
                    show_success_fn=lambda *_args, **_kwargs: None,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(ready)
        self.assertTrue(errors)
        self.assertEqual(errors[-1][0], "初始化失败")
        self.assertIn("OpenCode 状态目录", errors[-1][1] or "")
        self.assertIn(str(missing_state_auth.parent), errors[-1][1] or "")

    def test_cmd_init_returns_error_when_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "missing-openclaw-root"
            opencode_config = base / "opencode-config" / "opencode.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_config.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            output = io.StringIO()

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")
                with redirect_stdout(output):
                    exit_code = MODULE.cmd_init(
                        root=root,
                        openclaw_config_path=root / "openclaw.json",
                        opencode_config_path=opencode_config,
                        opencode_auth_path=opencode_auth,
                    )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertEqual(exit_code, 1)
        self.assertIn("初始化失败", output.getvalue())
        self.assertIn("OpenClAW 根目录", output.getvalue())


if __name__ == "__main__":
    unittest.main()
