import importlib.util
import io
import os
import subprocess
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
    def test_variant_requires_openclaw_login_excludes_opencode_mode(self) -> None:
        original_variant = MODULE.APP_VARIANT
        try:
            setattr(MODULE, "APP_VARIANT", "opencode")
            requires_openclaw_login = MODULE.variant_requires_openclaw_login()
        finally:
            setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertFalse(requires_openclaw_login)

    def test_load_store_migrates_legacy_store_into_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            hub_root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            legacy_store = {
                "version": 1,
                "active": "legacy",
                "accounts": {
                    "legacy": {
                        "type": "oauth",
                        "provider": MODULE.PROVIDER_KEY,
                        "access": "legacy-access",
                        "refresh": "legacy-refresh",
                        "expires": 1,
                        "accountId": "legacy-account",
                    }
                },
            }
            MODULE.write_json(
                openclaw_root / "openai-codex-accounts.json", legacy_store
            )

            original_root = MODULE.ROOT
            original_openclaw_root = getattr(MODULE, "OPENCLAW_ROOT", MODULE.ROOT)
            try:
                setattr(MODULE, "ROOT", hub_root)
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                loaded = MODULE.load_store(hub_root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

            self.assertEqual(loaded["active"], "legacy")
            self.assertEqual(
                loaded["accounts"]["legacy"]["accountId"], "legacy-account"
            )
            self.assertEqual(
                MODULE.read_json(hub_root / "openai-codex-accounts.json"), legacy_store
            )

    def test_load_app_state_migrates_legacy_state_into_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            hub_root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            legacy_state = {
                "initCompleted": True,
                "dashboardSnapshot": {
                    "rowsByAlias": {
                        "legacy": {
                            "alias": "legacy",
                            "displayName": "Legacy",
                            "accountId": "legacy-account",
                            "isCurrent": True,
                        }
                    }
                },
            }
            MODULE.write_json(openclaw_root / "openai-hub-state.json", legacy_state)

            original_root = MODULE.ROOT
            original_openclaw_root = getattr(MODULE, "OPENCLAW_ROOT", MODULE.ROOT)
            try:
                setattr(MODULE, "ROOT", hub_root)
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                loaded = MODULE.load_app_state(hub_root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

            self.assertTrue(loaded["initCompleted"])
            self.assertIn("legacy", loaded["dashboardSnapshot"]["rowsByAlias"])
            self.assertEqual(
                MODULE.read_json(hub_root / "openai-hub-state.json"), legacy_state
            )

    def test_load_store_falls_back_to_legacy_store_when_target_file_is_locked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            hub_root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            legacy_store = {
                "version": 1,
                "active": "legacy",
                "accounts": {
                    "legacy": {
                        "type": "oauth",
                        "provider": MODULE.PROVIDER_KEY,
                        "access": "legacy-access",
                        "refresh": "legacy-refresh",
                        "expires": 1,
                        "accountId": "legacy-account",
                    }
                },
            }
            MODULE.write_json(
                openclaw_root / "openai-codex-accounts.json", legacy_store
            )
            MODULE.write_json(hub_root / "openai-codex-accounts.json", {})

            original_root = MODULE.ROOT
            original_openclaw_root = getattr(MODULE, "OPENCLAW_ROOT", MODULE.ROOT)
            original_write_bytes_atomic = MODULE.write_bytes_atomic
            try:
                setattr(MODULE, "ROOT", hub_root)
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                setattr(
                    MODULE,
                    "write_bytes_atomic",
                    lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        PermissionError("locked")
                    ),
                )
                loaded = MODULE.load_store(hub_root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)
                setattr(MODULE, "write_bytes_atomic", original_write_bytes_atomic)

            self.assertEqual(loaded["active"], "legacy")
            self.assertEqual(
                loaded["accounts"]["legacy"]["accountId"], "legacy-account"
            )

    def test_extract_current_profile_error_points_to_resolved_openclaw_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            hub_root = base / ".openaihub"
            openclaw_root = base / ".openclaw-custom"

            original_root = MODULE.ROOT
            original_openclaw_root = getattr(MODULE, "OPENCLAW_ROOT", MODULE.ROOT)
            try:
                setattr(MODULE, "ROOT", hub_root)
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                with self.assertRaises(ValueError) as ctx:
                    MODULE.extract_current_profile(hub_root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

        self.assertIn(str(openclaw_root / "agents"), str(ctx.exception))

    def test_extract_current_profile_uses_openclaw_root_when_hub_root_is_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            hub_root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            agent_dir = openclaw_root / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            MODULE.write_json(
                agent_dir / "auth-profiles.json",
                {
                    "version": 1,
                    "profiles": {
                        MODULE.PROFILE_KEY: {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "live-access",
                            "refresh": "live-refresh",
                            "expires": 1,
                            "accountId": "live-account",
                        }
                    },
                    "lastGood": {MODULE.PROVIDER_KEY: MODULE.PROFILE_KEY},
                    "usageStats": {},
                },
            )

            original_root = MODULE.ROOT
            original_openclaw_root = getattr(MODULE, "OPENCLAW_ROOT", MODULE.ROOT)
            try:
                setattr(MODULE, "ROOT", hub_root)
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                profile = MODULE.extract_current_profile(hub_root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

        self.assertEqual(profile["accountId"], "live-account")
        self.assertEqual(
            MODULE.root_store_file(hub_root), hub_root / "openai-codex-accounts.json"
        )

    def test_switch_alias_restarts_openclaw_runtime_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agent_dir = root / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "auth.json").write_text(
                '{"openai-codex":{"type":"oauth","access":"old-access","refresh":"old-refresh","expires":1,"accountId":"old-account"}}\n',
                encoding="utf-8",
            )
            (agent_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{"openai-codex:default":{"type":"oauth","provider":"openai-codex","access":"old-access","refresh":"old-refresh","expires":1,"accountId":"old-account"}},"lastGood":{"openai-codex":"openai-codex:default"},"usageStats":{}}\n',
                encoding="utf-8",
            )
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "old",
                    "accounts": {
                        "old": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "old-access",
                            "refresh": "old-refresh",
                            "expires": 1,
                            "accountId": "old-account",
                        },
                        "bad": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "bad-access",
                            "refresh": "bad-refresh",
                            "expires": 0,
                            "accountId": "bad-account",
                        },
                    },
                },
                root,
            )

            restart_calls: list[str] = []

            def fake_restart() -> dict[str, object]:
                restart_calls.append("called")
                return {
                    "attempted": True,
                    "ok": True,
                    "command": ["openclaw", "gateway", "restart"],
                }

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "openclaw")
                result = MODULE.switch_alias(
                    root,
                    "bad",
                    restart_openclaw_runtime_fn=fake_restart,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

            self.assertEqual(restart_calls, ["called"])
            self.assertEqual(result["updatedAgentCount"], 1)
            self.assertTrue(result["openclawRuntimeRestart"]["ok"])

    def test_switch_alias_clears_openclaw_session_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agent_dir = root / "agents" / "main" / "agent"
            session_file = root / "agents" / "main" / "sessions" / "sessions.json"
            agent_dir.mkdir(parents=True, exist_ok=True)
            session_file.parent.mkdir(parents=True, exist_ok=True)
            (agent_dir / "auth.json").write_text(
                '{"openai-codex":{"type":"oauth","access":"old-access","refresh":"old-refresh","expires":1,"accountId":"old-account"}}\n',
                encoding="utf-8",
            )
            (agent_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{"openai-codex:default":{"type":"oauth","provider":"openai-codex","access":"old-access","refresh":"old-refresh","expires":1,"accountId":"old-account"}},"lastGood":{"openai-codex":"openai-codex:default"},"usageStats":{}}\n',
                encoding="utf-8",
            )
            session_file.write_text(
                '{"agent:main:webchat:test":{"providerOverride":"custom-127-0-0-1-8045","modelOverride":"claude-opus-4-6","authProfileOverride":"openai-codex:default","authProfileOverrideSource":"auto","authProfileOverrideCompactionCount":3,"displayName":"test"}}\n',
                encoding="utf-8",
            )
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.write_text('{"openai":{}}\n', encoding="utf-8")
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "old",
                    "accounts": {
                        "old": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "old-access",
                            "refresh": "old-refresh",
                            "expires": 1,
                            "accountId": "old-account",
                        },
                        "bad": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "bad-access",
                            "refresh": "bad-refresh",
                            "expires": 0,
                            "accountId": "bad-account",
                        },
                    },
                },
                root,
            )

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")
                MODULE.switch_alias(
                    root,
                    "bad",
                    opencode_auth_path=opencode_auth,
                    restart_openclaw_runtime_fn=lambda: {
                        "attempted": True,
                        "ok": True,
                    },
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

            sessions = MODULE.read_json(session_file)
            session = sessions["agent:main:webchat:test"]
            self.assertNotIn("providerOverride", session)
            self.assertNotIn("modelOverride", session)
            self.assertNotIn("authProfileOverride", session)
            self.assertNotIn("authProfileOverrideSource", session)
            self.assertNotIn("authProfileOverrideCompactionCount", session)

    def test_switch_alias_updates_dashboard_snapshot_current_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agent_dir = root / "agents" / "main" / "agent"
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "auth.json").write_text(
                '{"openai-codex":{"type":"oauth","access":"bad-access","refresh":"bad-refresh","expires":0,"accountId":"bad-account"}}\n',
                encoding="utf-8",
            )
            (agent_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{"openai-codex:default":{"type":"oauth","provider":"openai-codex","access":"bad-access","refresh":"bad-refresh","expires":0,"accountId":"bad-account"}},"lastGood":{"openai-codex":"openai-codex:default"},"usageStats":{}}\n',
                encoding="utf-8",
            )
            MODULE.write_json(
                root / "openai-hub-state.json",
                {
                    "dashboardSnapshot": {
                        "rowsByAlias": {
                            "bad": {
                                "alias": "bad",
                                "displayName": "Bad Account",
                                "accountId": "bad-account",
                                "isCurrent": True,
                                "plan": "team",
                                "windows": [],
                                "groups": [],
                                "error": "登录凭证需要重新登录，已暂停自动检测（剩余 15分0秒）",
                                "warning": None,
                                "_authIssueStatus": 401,
                                "_authIssueCount": 3,
                                "_authIssueFirstAtMs": 123,
                                "_authBlockedUntilMs": 456,
                                "_authBlockedRefresh": "bad-refresh",
                            },
                            "good": {
                                "alias": "good",
                                "displayName": "Good Account",
                                "accountId": "good-account",
                                "isCurrent": False,
                                "plan": "team",
                                "windows": [],
                                "groups": [],
                                "error": None,
                                "warning": None,
                            },
                        }
                    }
                },
            )
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            opencode_auth.write_text('{"openai":{}}\n', encoding="utf-8")
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "bad",
                    "accounts": {
                        "bad": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "bad-access",
                            "refresh": "bad-refresh",
                            "expires": 0,
                            "accountId": "bad-account",
                            "displayName": "Bad Account",
                        },
                        "good": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "good-access",
                            "refresh": "good-refresh",
                            "expires": 99,
                            "accountId": "good-account",
                            "displayName": "Good Account",
                        },
                    },
                },
                root,
            )

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")
                MODULE.switch_alias(
                    root,
                    "good",
                    opencode_auth_path=opencode_auth,
                    restart_openclaw_runtime_fn=lambda: {
                        "attempted": True,
                        "ok": True,
                    },
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

            state = MODULE.read_json(root / "openai-hub-state.json")
            rows = state["dashboardSnapshot"]["rowsByAlias"]
            self.assertFalse(rows["bad"]["isCurrent"])
            self.assertTrue(rows["good"]["isCurrent"])
            self.assertEqual(rows["good"]["accountId"], "good-account")
            self.assertIsNone(rows["good"].get("error"))
            self.assertIsNone(rows["good"].get("warning"))
            self.assertIsNone(rows["good"].get("_authBlockedRefresh"))
            self.assertNotIn("_authBlockedUntilMs", rows["good"])

    def test_full_mode_allows_valid_paths_when_program_and_provider_probes_fail(
        self,
    ) -> None:
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

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")

                verification = MODULE.verify_initialized_environment(
                    root=root,
                    openclaw_config_path=root / "openclaw.json",
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    openclaw_program_probe_fn=lambda: False,
                    opencode_program_probe_fn=lambda: False,
                    openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: False,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertTrue(verification.get("ok"))

    def test_probe_switch_targets_writes_and_restores_real_target_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            auth_path = agents_dir / "auth.json"
            profiles_path = agents_dir / "auth-profiles.json"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)

            auth_payload = {
                MODULE.PROVIDER_KEY: {
                    "type": "oauth",
                    "access": "old-access",
                    "refresh": "old-refresh",
                    "expires": 1,
                    "accountId": "old-account",
                }
            }
            profiles_payload = {
                "version": 1,
                "profiles": {
                    MODULE.PROFILE_KEY: {
                        "type": "oauth",
                        "provider": MODULE.PROVIDER_KEY,
                        "access": "old-access",
                        "refresh": "old-refresh",
                        "expires": 1,
                        "accountId": "old-account",
                    }
                },
                "lastGood": {MODULE.PROVIDER_KEY: MODULE.PROFILE_KEY},
                "usageStats": {MODULE.PROFILE_KEY: {"lastUsed": 0, "errorCount": 0}},
            }
            opencode_payload = {
                "openai": {
                    "type": "oauth",
                    "access": "old-access",
                    "refresh": "old-refresh",
                    "expires": 1,
                    "accountId": "old-account",
                }
            }
            MODULE.write_json(auth_path, auth_payload)
            MODULE.write_json(profiles_path, profiles_payload)
            MODULE.write_json(opencode_auth, opencode_payload)

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "full")
                failure = MODULE.probe_switch_targets(
                    root=root, opencode_auth_path=opencode_auth
                )
                restored_auth = MODULE.read_json(auth_path)
                restored_profiles = MODULE.read_json(profiles_path)
                restored_opencode = MODULE.read_json(opencode_auth)
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertIsNone(failure)
        self.assertEqual(restored_auth, auth_payload)
        self.assertEqual(restored_profiles, profiles_payload)
        self.assertEqual(restored_opencode, opencode_payload)

    def test_probe_openclaw_switch_target_writes_and_restores_live_auth_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            auth_path = agents_dir / "auth.json"
            profiles_path = agents_dir / "auth-profiles.json"
            auth_payload = {
                MODULE.PROVIDER_KEY: {
                    "type": "oauth",
                    "access": "live-access",
                    "refresh": "live-refresh",
                    "expires": 1,
                    "accountId": "live-account",
                }
            }
            profiles_payload = {
                "version": 1,
                "profiles": {
                    MODULE.PROFILE_KEY: {
                        "type": "oauth",
                        "provider": MODULE.PROVIDER_KEY,
                        "access": "live-access",
                        "refresh": "live-refresh",
                        "expires": 1,
                        "accountId": "live-account",
                    }
                },
                "lastGood": {MODULE.PROVIDER_KEY: MODULE.PROFILE_KEY},
                "usageStats": {MODULE.PROFILE_KEY: {"lastUsed": 0, "errorCount": 0}},
            }
            MODULE.write_json(auth_path, auth_payload)
            MODULE.write_json(profiles_path, profiles_payload)

            original_write_json = MODULE.write_json
            original_write_bytes_atomic = MODULE.write_bytes_atomic

            writes: list[Path] = []
            restores: list[Path] = []

            def guarded_write_json(path: Path, data):
                if path in {auth_path, profiles_path}:
                    writes.append(path)
                return original_write_json(path, data)

            def guarded_write_bytes_atomic(path: Path, data: bytes):
                if path in {auth_path, profiles_path}:
                    restores.append(path)
                return original_write_bytes_atomic(path, data)

            setattr(MODULE, "write_json", guarded_write_json)
            setattr(MODULE, "write_bytes_atomic", guarded_write_bytes_atomic)
            try:
                MODULE.probe_openclaw_agent_switch_target(agents_dir)
            finally:
                setattr(MODULE, "write_json", original_write_json)
                setattr(MODULE, "write_bytes_atomic", original_write_bytes_atomic)

            self.assertGreaterEqual(writes.count(auth_path), 1)
            self.assertGreaterEqual(writes.count(profiles_path), 1)
            self.assertGreaterEqual(restores.count(auth_path), 1)
            self.assertGreaterEqual(restores.count(profiles_path), 1)
            self.assertEqual(MODULE.read_json(auth_path), auth_payload)
            self.assertEqual(MODULE.read_json(profiles_path), profiles_payload)

    def test_restart_openclaw_runtime_after_switch_handles_missing_command(
        self,
    ) -> None:
        original_resolve = MODULE.resolve_openclaw_gateway_restart_command
        original_resolve_helper = getattr(
            MODULE, "resolve_openclaw_restart_helper_script_posix", None
        )
        original_resolve_program = MODULE.resolve_openclaw_program_command
        try:
            setattr(
                MODULE,
                "resolve_openclaw_gateway_restart_command",
                lambda appdata=None: None,
            )
            setattr(
                MODULE,
                "resolve_openclaw_restart_helper_script_posix",
                lambda: None,
            )
            setattr(
                MODULE, "resolve_openclaw_program_command", lambda appdata=None: None
            )
            result = MODULE.restart_openclaw_runtime_after_switch(
                platform_name="posix",
                gateway_launcher_path=None,
            )
        finally:
            setattr(
                MODULE, "resolve_openclaw_gateway_restart_command", original_resolve
            )
            if original_resolve_helper is None:
                delattr(MODULE, "resolve_openclaw_restart_helper_script_posix")
            else:
                setattr(
                    MODULE,
                    "resolve_openclaw_restart_helper_script_posix",
                    original_resolve_helper,
                )
            setattr(
                MODULE, "resolve_openclaw_program_command", original_resolve_program
            )

        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "command-unavailable")

    def test_restart_openclaw_runtime_after_switch_runs_gateway_restart(self) -> None:
        original_resolve = MODULE.resolve_openclaw_gateway_restart_command
        original_resolve_helper = getattr(
            MODULE, "resolve_openclaw_restart_helper_script_posix", None
        )
        original_resolve_program = MODULE.resolve_openclaw_program_command

        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="gateway restarted\n",
                stderr="",
            )

        try:
            setattr(
                MODULE,
                "resolve_openclaw_gateway_restart_command",
                lambda appdata=None: ["openclaw", "gateway", "restart"],
            )
            setattr(
                MODULE,
                "resolve_openclaw_restart_helper_script_posix",
                lambda: None,
            )
            setattr(
                MODULE, "resolve_openclaw_program_command", lambda appdata=None: None
            )
            result = MODULE.restart_openclaw_runtime_after_switch(
                subprocess_run=fake_run,
                platform_name="posix",
                gateway_launcher_path=None,
            )
        finally:
            setattr(
                MODULE, "resolve_openclaw_gateway_restart_command", original_resolve
            )
            if original_resolve_helper is None:
                delattr(MODULE, "resolve_openclaw_restart_helper_script_posix")
            else:
                setattr(
                    MODULE,
                    "resolve_openclaw_restart_helper_script_posix",
                    original_resolve_helper,
                )
            setattr(
                MODULE, "resolve_openclaw_program_command", original_resolve_program
            )

        self.assertEqual(captured, [["openclaw", "gateway", "restart"]])
        self.assertTrue(result["attempted"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "gateway restarted")

    def test_restart_openclaw_runtime_after_switch_spawns_visible_helper_on_windows(
        self,
    ) -> None:
        popen_calls: list[tuple[list[str], dict[str, object]]] = []

        class FakeProcess:
            pid = 1234

        def fake_popen(command, **kwargs):
            popen_calls.append((command, kwargs))
            return FakeProcess()

        original_resolve_program = MODULE.resolve_openclaw_program_command
        original_resolve_helper = MODULE.resolve_openclaw_restart_helper_script
        try:
            setattr(
                MODULE,
                "resolve_openclaw_program_command",
                lambda appdata=None: r"C:\Users\maobin666\AppData\Roaming\npm\openclaw.cmd",
            )
            setattr(
                MODULE,
                "resolve_openclaw_restart_helper_script",
                lambda: Path(r"C:\repo\package\app\openclaw_restart_gateway.ps1"),
            )
            result = MODULE.restart_openclaw_runtime_after_switch(
                subprocess_popen=fake_popen,
                platform_name="nt",
                gateway_launcher_path=Path(r"C:\Users\maobin666\.openclaw\gateway.cmd"),
            )
        finally:
            setattr(
                MODULE, "resolve_openclaw_program_command", original_resolve_program
            )
            setattr(
                MODULE,
                "resolve_openclaw_restart_helper_script",
                original_resolve_helper,
            )

        self.assertEqual(
            popen_calls,
            [
                (
                    [
                        "cmd",
                        "/c",
                        "start",
                        "",
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        r"C:\repo\package\app\openclaw_restart_gateway.ps1",
                        "-OpenClawCmd",
                        r"C:\Users\maobin666\AppData\Roaming\npm\openclaw.cmd",
                        "-GatewayLauncher",
                        r"C:\Users\maobin666\.openclaw\gateway.cmd",
                    ],
                    {"close_fds": True},
                )
            ],
        )
        self.assertTrue(result["attempted"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "visible-stop-start-script")

    def test_restart_openclaw_runtime_after_switch_spawns_helper_on_posix(self) -> None:
        popen_calls: list[tuple[list[str], dict[str, object]]] = []

        class FakeProcess:
            pid = 5678

        def fake_popen(command, **kwargs):
            popen_calls.append((command, kwargs))
            return FakeProcess()

        original_resolve_program = MODULE.resolve_openclaw_program_command
        original_resolve_helper = getattr(
            MODULE, "resolve_openclaw_restart_helper_script_posix", None
        )
        try:
            setattr(
                MODULE,
                "resolve_openclaw_program_command",
                lambda appdata=None: "/usr/local/bin/openclaw",
            )
            setattr(
                MODULE,
                "resolve_openclaw_restart_helper_script_posix",
                lambda: Path("/repo/package/app/openclaw_restart_gateway.sh"),
            )
            result = MODULE.restart_openclaw_runtime_after_switch(
                subprocess_popen=fake_popen,
                platform_name="posix",
                gateway_launcher_path=None,
            )
        finally:
            setattr(
                MODULE, "resolve_openclaw_program_command", original_resolve_program
            )
            if original_resolve_helper is None:
                delattr(MODULE, "resolve_openclaw_restart_helper_script_posix")
            else:
                setattr(
                    MODULE,
                    "resolve_openclaw_restart_helper_script_posix",
                    original_resolve_helper,
                )

        self.assertEqual(
            popen_calls,
            [
                (
                    [
                        "sh",
                        str(Path("/repo/package/app/openclaw_restart_gateway.sh")),
                        "/usr/local/bin/openclaw",
                    ],
                    {"close_fds": True, "start_new_session": True},
                )
            ],
        )
        self.assertTrue(result["attempted"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "posix-stop-start-script")

    def test_resolve_openclaw_gateway_restart_command_prefers_appdata_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            appdata = Path(tmp_dir) / "Roaming"
            npm_dir = appdata / "npm"
            npm_dir.mkdir(parents=True, exist_ok=True)
            (npm_dir / "openclaw.cmd").write_text("@echo off\n", encoding="utf-8")

            original_is_installed = MODULE.is_openclaw_program_installed
            original_bundled = MODULE.resolve_bundled_openclaw_entry
            original_which = MODULE.shutil.which
            try:
                setattr(
                    MODULE,
                    "is_openclaw_program_installed",
                    lambda executable="openclaw": False,
                )
                setattr(MODULE, "resolve_bundled_openclaw_entry", lambda: None)
                MODULE.shutil.which = lambda _name: None
                command = MODULE.resolve_openclaw_gateway_restart_command(str(appdata))
            finally:
                setattr(MODULE, "is_openclaw_program_installed", original_is_installed)
                setattr(MODULE, "resolve_bundled_openclaw_entry", original_bundled)
                MODULE.shutil.which = original_which

        self.assertEqual(command, [str(npm_dir / "openclaw.cmd"), "gateway", "restart"])

    def test_resolve_openclaw_root_prefers_openclaw_state_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_root = Path(tmp_dir) / "custom-openclaw"
            env_root.mkdir(parents=True, exist_ok=True)

            original_env = os.environ.get("OPENCLAW_STATE_DIR")
            try:
                os.environ["OPENCLAW_STATE_DIR"] = str(env_root)
                resolved = MODULE.resolve_openclaw_root(Path(tmp_dir) / ".openaihub")
            finally:
                if original_env is None:
                    os.environ.pop("OPENCLAW_STATE_DIR", None)
                else:
                    os.environ["OPENCLAW_STATE_DIR"] = original_env

        self.assertEqual(resolved, env_root)

    def test_resolve_opencode_auth_file_prefers_macos_library_path_when_present(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            library_auth = (
                home / "Library" / "Application Support" / "opencode" / "auth.json"
            )
            library_auth.parent.mkdir(parents=True, exist_ok=True)
            library_auth.write_text("{}", encoding="utf-8")

            original_platform = MODULE.sys.platform
            original_home = MODULE.Path.home
            original_xdg_data_home = os.environ.get("XDG_DATA_HOME")
            try:
                MODULE.sys.platform = "darwin"
                MODULE.Path.home = classmethod(lambda cls: home)
                os.environ.pop("XDG_DATA_HOME", None)
                resolved = MODULE.resolve_opencode_auth_file()
            finally:
                MODULE.sys.platform = original_platform
                MODULE.Path.home = original_home
                if original_xdg_data_home is None:
                    os.environ.pop("XDG_DATA_HOME", None)
                else:
                    os.environ["XDG_DATA_HOME"] = original_xdg_data_home

        self.assertEqual(resolved, library_auth)

    def test_probe_opencode_switch_target_writes_and_restores_live_auth_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            auth_path = base / "opencode-state" / "auth.json"
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            auth_payload = {
                "openai": {
                    "type": "oauth",
                    "access": "live-access",
                    "refresh": "live-refresh",
                    "expires": 1,
                    "accountId": "live-account",
                }
            }
            MODULE.write_json(auth_path, auth_payload)

            original_write_json = MODULE.write_json
            original_write_bytes_atomic = MODULE.write_bytes_atomic

            writes: list[Path] = []
            restores: list[Path] = []

            def guarded_write_json(path: Path, data):
                if path == auth_path:
                    writes.append(path)
                return original_write_json(path, data)

            def guarded_write_bytes_atomic(path: Path, data: bytes):
                if path == auth_path:
                    restores.append(path)
                return original_write_bytes_atomic(path, data)

            setattr(MODULE, "write_json", guarded_write_json)
            setattr(MODULE, "write_bytes_atomic", guarded_write_bytes_atomic)
            try:
                MODULE.probe_opencode_switch_target(auth_path)
            finally:
                setattr(MODULE, "write_json", original_write_json)
                setattr(MODULE, "write_bytes_atomic", original_write_bytes_atomic)

            self.assertGreaterEqual(writes.count(auth_path), 1)
            self.assertGreaterEqual(restores.count(auth_path), 1)
            self.assertEqual(MODULE.read_json(auth_path), auth_payload)

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

    def test_switch_alias_in_opencode_mode_does_not_require_openclaw_runtime_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            opencode_auth = base / "opencode-state" / "auth.json"
            opencode_auth.parent.mkdir(parents=True, exist_ok=True)
            MODULE.write_json(opencode_auth, {})
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "source",
                    "accounts": {
                        "source": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "source-access",
                            "refresh": "source-refresh",
                            "expires": 1,
                            "accountId": "source-account",
                        },
                        "target": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "target-access",
                            "refresh": "target-refresh",
                            "expires": 2,
                            "accountId": "target-account",
                        },
                    },
                },
                root,
            )

            original_variant = MODULE.APP_VARIANT
            original_openclaw_root = MODULE.OPENCLAW_ROOT
            try:
                setattr(MODULE, "APP_VARIANT", "opencode")
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                result = MODULE.switch_alias(
                    root, "target", opencode_auth_path=opencode_auth
                )
                written_auth = MODULE.read_json(opencode_auth)
                written_store = MODULE.load_store(root)
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

        self.assertEqual(result["updatedAgentCount"], 0)
        self.assertEqual(written_auth["openai"]["refresh"], "target-refresh")
        self.assertEqual(written_store["active"], "target")

    def test_cmd_usage_in_opencode_mode_uses_selected_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "saved",
                    "accounts": {
                        "saved": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "saved-access",
                            "refresh": "saved-refresh",
                            "expires": 3,
                            "accountId": "saved-account",
                            "displayName": "Saved Account",
                        }
                    },
                },
                root,
            )

            original_root = MODULE.ROOT
            original_variant = MODULE.APP_VARIANT
            original_openclaw_root = MODULE.OPENCLAW_ROOT
            original_fetch = MODULE.fetch_codex_usage
            output = io.StringIO()
            try:
                setattr(MODULE, "ROOT", root)
                setattr(MODULE, "APP_VARIANT", "opencode")
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                setattr(
                    MODULE,
                    "fetch_codex_usage",
                    lambda profile: {
                        "plan": "team",
                        "windows": [
                            {"label": "5h", "usedPercent": 12.0, "resetAt": None}
                        ],
                    },
                )
                with redirect_stdout(output):
                    exit_code = MODULE.cmd_usage()
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "APP_VARIANT", original_variant)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)
                setattr(MODULE, "fetch_codex_usage", original_fetch)

        self.assertEqual(exit_code, 0)
        self.assertIn("Saved Account", output.getvalue())
        self.assertIn("saved-account", output.getvalue())

    def test_detect_current_alias_in_opencode_mode_uses_selected_saved_alias(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / ".openaihub"
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "selected",
                    "accounts": {
                        "selected": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "selected-access",
                            "refresh": "selected-refresh",
                            "expires": 4,
                            "accountId": "selected-account",
                        }
                    },
                },
                root,
            )

            original_variant = MODULE.APP_VARIANT
            try:
                setattr(MODULE, "APP_VARIANT", "opencode")
                alias = MODULE.detect_current_alias(root)
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)

        self.assertEqual(alias, "selected")

    def test_cmd_save_in_opencode_mode_uses_selected_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / ".openaihub"
            openclaw_root = base / ".openclaw"
            MODULE.save_store(
                {
                    "version": 1,
                    "active": "selected",
                    "accounts": {
                        "selected": {
                            "type": "oauth",
                            "provider": MODULE.PROVIDER_KEY,
                            "access": "selected-access",
                            "refresh": "selected-refresh",
                            "expires": 5,
                            "accountId": "selected-account",
                            "displayName": "Selected Account",
                        }
                    },
                },
                root,
            )

            original_root = MODULE.ROOT
            original_variant = MODULE.APP_VARIANT
            original_openclaw_root = MODULE.OPENCLAW_ROOT
            output = io.StringIO()
            try:
                setattr(MODULE, "ROOT", root)
                setattr(MODULE, "APP_VARIANT", "opencode")
                setattr(MODULE, "OPENCLAW_ROOT", openclaw_root)
                with redirect_stdout(output):
                    exit_code = MODULE.cmd_save("snapshot")
                written_store = MODULE.load_store(root)
            finally:
                setattr(MODULE, "ROOT", original_root)
                setattr(MODULE, "APP_VARIANT", original_variant)
                setattr(MODULE, "OPENCLAW_ROOT", original_openclaw_root)

        self.assertEqual(exit_code, 0)
        self.assertEqual(written_store["active"], "snapshot")
        self.assertEqual(
            written_store["accounts"]["snapshot"]["accountId"], "selected-account"
        )
        self.assertEqual(
            written_store["accounts"]["snapshot"]["refresh"], "selected-refresh"
        )
        self.assertIn("已保存账号别名：snapshot", output.getvalue())
        self.assertIn("selected-account", output.getvalue())

    def test_full_mode_allows_menu_when_openclaw_program_not_installed_but_paths_valid(
        self,
    ) -> None:
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

        self.assertTrue(ready)

    def test_full_mode_allows_menu_without_custom_openclaw_provider_models(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (root / "openclaw.json").write_text("{}\n", encoding="utf-8")
            (agents_dir / "models.json").write_text("{}\n", encoding="utf-8")
            (agents_dir / "auth.json").write_text(
                '{"openai-codex":{"type":"oauth","refresh":"token"}}\n',
                encoding="utf-8",
            )
            (agents_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{"openai-codex:default":{"type":"oauth","provider":"openai-codex","refresh":"token"}},"lastGood":{"openai-codex":"openai-codex:default"},"usageStats":{}}\n',
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
                        **kwargs,
                    ),
                    verify_fn=lambda **kwargs: MODULE.verify_initialized_environment(
                        openclaw_program_probe_fn=lambda: True,
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

        self.assertTrue(ready)
        self.assertFalse(errors)

    def test_initialize_environment_does_not_rewrite_openclaw_model_config(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            root = base / "openclaw-root"
            agents_dir = root / "agents" / "main" / "agent"
            agents_dir.mkdir(parents=True, exist_ok=True)
            openclaw_config = root / "openclaw.json"
            models_path = agents_dir / "models.json"
            openclaw_config.write_text("{}\n", encoding="utf-8")
            models_path.write_text("{}\n", encoding="utf-8")
            (agents_dir / "auth.json").write_text(
                '{"openai-codex":{"type":"oauth","refresh":"token"}}\n',
                encoding="utf-8",
            )
            (agents_dir / "auth-profiles.json").write_text(
                '{"version":1,"profiles":{"openai-codex:default":{"type":"oauth","provider":"openai-codex","refresh":"token"}},"lastGood":{"openai-codex":"openai-codex:default"},"usageStats":{}}\n',
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

            original_write_json_with_backup = MODULE.write_json_with_backup

            def guarded_write_json_with_backup(path: Path, data):
                if path in {openclaw_config, models_path}:
                    raise AssertionError(f"openclaw config rewrite attempted: {path}")
                return original_write_json_with_backup(path, data)

            original_variant = MODULE.APP_VARIANT
            setattr(MODULE, "write_json_with_backup", guarded_write_json_with_backup)
            try:
                setattr(MODULE, "APP_VARIANT", "full")
                summary = MODULE.initialize_environment(
                    root=root,
                    openclaw_config_path=openclaw_config,
                    opencode_config_path=opencode_config,
                    opencode_auth_path=opencode_auth,
                    openclaw_program_probe_fn=lambda: True,
                    opencode_program_probe_fn=lambda: True,
                    openclaw_provider_probe_fn=lambda _provider_id=MODULE.PROVIDER_KEY: True,
                )
            finally:
                setattr(MODULE, "APP_VARIANT", original_variant)
                setattr(
                    MODULE, "write_json_with_backup", original_write_json_with_backup
                )

        self.assertTrue(summary.get("verification", {}).get("ok"))

    def test_full_mode_allows_menu_when_opencode_program_not_installed_but_paths_valid(
        self,
    ) -> None:
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

        self.assertTrue(ready)

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
