import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import requests


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "package"
    / "app"
    / "openclaw_oauth_switcher.py"
)
SPEC = importlib.util.spec_from_file_location(
    "openclaw_oauth_switcher_region", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DummyResponse(requests.Response):
    def __init__(self, status_code: int, payload: dict[str, object], url: str) -> None:
        super().__init__()
        self.status_code = status_code
        self.url = url
        self._content = b"{}"
        self._payload = payload

    def raise_for_status(self) -> None:
        raise requests.HTTPError(response=self)

    def json(self, **_kwargs):
        return self._payload


class LoginRegionRestrictionTests(unittest.TestCase):
    def test_init_success_detail_marks_remote_auth_unverified(self) -> None:
        detail = MODULE.build_init_success_detail("自动登录助手")

        self.assertIn("本地初始化", detail)
        self.assertIn("未验证 OpenAI 账号地区/网络资格", detail)

    def test_complete_login_session_translates_region_restriction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            session_file = MODULE.login_session_file(root)
            session_file.parent.mkdir(parents=True, exist_ok=True)
            MODULE.write_json(
                session_file,
                {"state": "abc", "verifier": "verifier", "createdAt": "now"},
            )

            response = DummyResponse(
                403,
                {
                    "error": {
                        "code": "unsupported_country_region_territory",
                        "message": "Country, region, or territory not supported",
                    }
                },
                MODULE.TOKEN_URL,
            )

            def failing_post(*_args, **_kwargs):
                return response

            with self.assertRaises(ValueError) as ctx:
                MODULE.complete_login_session(
                    root,
                    "http://localhost:1455/auth/callback?code=ok&state=abc",
                    requests_post=failing_post,
                )

        self.assertIn("当前网络出口或地区不受 OpenAI 支持", str(ctx.exception))

    def test_cmd_add_does_not_fallback_when_region_is_restricted(self) -> None:
        original_login_helper_available = MODULE.login_helper_available
        original_manual_fallback = MODULE.add_account_via_manual_callback_fallback
        manual_called = {"value": False}

        def fail_login_helper():
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["node", "helper.mjs"],
                stderr=(
                    '[openai-codex] code->token failed: 403 {"error":{"code":'
                    '"unsupported_country_region_territory","message":'
                    '"Country, region, or territory not supported"}}'
                ),
            )

        def unexpected_manual_fallback(*_args, **_kwargs):
            manual_called["value"] = True
            raise AssertionError("manual fallback should not run")

        try:
            setattr(MODULE, "login_helper_available", lambda: True)
            setattr(
                MODULE,
                "add_account_via_manual_callback_fallback",
                unexpected_manual_fallback,
            )
            with self.assertRaises(ValueError) as ctx:
                with redirect_stdout(io.StringIO()):
                    MODULE.cmd_add(helper_login_fn=fail_login_helper)
        finally:
            setattr(MODULE, "login_helper_available", original_login_helper_available)
            setattr(
                MODULE,
                "add_account_via_manual_callback_fallback",
                original_manual_fallback,
            )

        self.assertFalse(manual_called["value"])
        self.assertIn("当前网络出口或地区不受 OpenAI 支持", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
