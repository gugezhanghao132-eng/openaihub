import importlib.util
import sys
import unittest
from pathlib import Path

import requests


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "package"
    / "app"
    / "openclaw_oauth_switcher.py"
)
SPEC = importlib.util.spec_from_file_location("openclaw_oauth_switcher", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_http_error(status_code: int, url: str | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response.url = url or MODULE.USAGE_URL
    return requests.HTTPError(response=response)


def make_previous_row() -> dict[str, object]:
    return {
        "alias": "alpha",
        "displayName": "Alpha",
        "accountId": "acct_alpha",
        "isCurrent": True,
        "plan": "plus",
        "windows": [
            {"label": "5h", "usedPercent": 20.0, "resetAt": None},
            {"label": "7d", "usedPercent": 10.0, "resetAt": None},
        ],
        "groups": [{"accountId": "acct_alpha", "name": "当前工作组", "windows": []}],
        "error": None,
        "warning": None,
    }


def make_profile() -> dict[str, object]:
    return {
        "email": "alpha@example.com",
        "access": "token",
        "refresh": "refresh",
        "accountId": "acct_alpha",
        "expires": 9999999999999,
    }


class DashboardAuthToleranceTests(unittest.TestCase):
    def test_build_panel_header_line_includes_version(self) -> None:
        header = MODULE.build_panel_header_line()

        self.assertIn(MODULE.APP_RELEASE_VERSION, header)

    def test_default_console_height_increased(self) -> None:
        self.assertEqual(MODULE.DEFAULT_WINDOW_LINES, 33)

    def test_render_home_dashboard_text_shows_current_variant_badge(self) -> None:
        row = make_previous_row()
        original_variant = MODULE.get_app_variant()
        try:
            MODULE.set_app_variant("openclaw")
            text = MODULE.render_home_dashboard_text([row], "alpha")
        finally:
            MODULE.set_app_variant(original_variant)

        first_line = text.splitlines()[0]
        self.assertIn("账号中心", first_line)
        self.assertIn("OpenClAW 模式", text)
        self.assertIn("OpenClAW 模式", first_line)

    def test_overview_body_viewport_shows_more_below_hint_when_truncated(self) -> None:
        lines = [f"line-{index}" for index in range(6)]

        visible_lines, normalized_offset, has_above, has_below = (
            MODULE.slice_overview_body_lines(lines, scroll_offset=0, viewport_height=3)
        )

        self.assertEqual(visible_lines, ["line-0", "line-1", "line-2"])
        self.assertEqual(normalized_offset, 0)
        self.assertFalse(has_above)
        self.assertTrue(has_below)

    def test_overview_body_viewport_clamps_offset_and_shows_more_above(self) -> None:
        lines = [f"line-{index}" for index in range(6)]

        visible_lines, normalized_offset, has_above, has_below = (
            MODULE.slice_overview_body_lines(lines, scroll_offset=99, viewport_height=3)
        )

        self.assertEqual(visible_lines, ["line-3", "line-4", "line-5"])
        self.assertEqual(normalized_offset, 3)
        self.assertTrue(has_above)
        self.assertFalse(has_below)

    def test_render_overview_screen_shows_scroll_hints_for_small_viewport(self) -> None:
        rows = []
        for index in range(6):
            row = make_previous_row()
            row["alias"] = f"alias-{index}"
            row["displayName"] = f"Account-{index}"
            row["accountId"] = f"acct-{index}"
            row["isCurrent"] = index == 0
            rows.append(row)

        text = MODULE.render_overview_screen(
            rows,
            "all",
            scroll_offset=0,
            body_viewport_height=6,
        )

        self.assertIn("↓ 继续查看下面账号", text)
        self.assertNotIn("↑ 上面还有账号", text)

    def test_render_overview_screen_keeps_total_lines_within_viewport_budget(
        self,
    ) -> None:
        rows = []
        for index in range(8):
            row = make_previous_row()
            row["alias"] = f"alias-{index}"
            row["displayName"] = f"Account-{index}"
            row["accountId"] = f"acct-{index}"
            row["isCurrent"] = index == 0
            rows.append(row)

        state = MODULE.build_overview_screen_state(
            rows,
            "all",
            scroll_offset=3,
            body_viewport_height=6,
        )
        text = str(state["text"])
        total_lines = len(text.splitlines())

        self.assertLessEqual(total_lines, 8)
        self.assertTrue(state["hasAbove"])
        self.assertTrue(state["hasBelow"])

    def test_refresh_endpoint_401_immediately_blocks_account(self) -> None:
        previous_row = make_previous_row()
        profile = make_profile()
        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: (_ for _ in ()).throw(
                make_http_error(401, url=MODULE.TOKEN_URL)
            ),
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNotNone(row["error"])
        self.assertIn("重新登录", row["error"])
        self.assertGreater(int(row.get("_authBlockedUntilMs") or 0), 0)
        self.assertEqual(row.get("_authBlockedRefresh"), profile["refresh"])

    def test_refresh_endpoint_400_also_blocks_account(self) -> None:
        previous_row = make_previous_row()
        profile = make_profile()
        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: (_ for _ in ()).throw(
                make_http_error(400, url=MODULE.TOKEN_URL)
            ),
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNotNone(row["error"])
        self.assertIn("重新登录", row["error"])
        self.assertGreater(int(row.get("_authBlockedUntilMs") or 0), 0)

    def test_blocked_account_skips_fetch_until_cooldown_expires(self) -> None:
        previous_row = {
            **make_previous_row(),
            "_authBlockedUntilMs": MODULE.current_time_ms() + 60_000,
            "_authIssueStatus": 401,
            "_authIssueCount": 99,
            "_authBlockedRefresh": "refresh",
        }
        profile = make_profile()

        def fail_if_called(_: object) -> dict[str, object]:
            raise AssertionError("fetch_usage should not be called for blocked account")

        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            fail_if_called,
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNotNone(row["error"])
        self.assertIn("暂停自动检测", row["error"])
        self.assertEqual(row["plan"], previous_row["plan"])

    def test_blocked_account_rechecks_after_refresh_token_changes(self) -> None:
        previous_row = {
            **make_previous_row(),
            "_authBlockedUntilMs": MODULE.current_time_ms() + 60_000,
            "_authIssueStatus": 401,
            "_authIssueCount": 99,
            "_authBlockedRefresh": "old-refresh",
        }
        profile = {**make_profile(), "refresh": "new-refresh"}

        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: {
                "plan": "plus",
                "windows": [{"label": "5h", "usedPercent": 22.0, "resetAt": None}],
            },
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNone(row["error"])
        self.assertEqual(row["plan"], "plus")

    def test_first_401_keeps_previous_snapshot_as_warning(self) -> None:
        previous_row = make_previous_row()
        profile = make_profile()
        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: (_ for _ in ()).throw(make_http_error(401)),
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNone(row["error"])
        self.assertEqual(row["plan"], previous_row["plan"])
        self.assertEqual(row["windows"], previous_row["windows"])
        self.assertEqual(row["groups"], previous_row["groups"])
        self.assertIn("鉴权接口临时波动", row["warning"])
        self.assertEqual(row["_authIssueStatus"], 401)
        self.assertEqual(row["_authIssueCount"], 1)

    def test_consecutive_401_over_grace_limit_becomes_error(self) -> None:
        previous_row = {
            **make_previous_row(),
            "_authIssueStatus": 401,
            "_authIssueCount": MODULE.DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS,
            "_authIssueFirstAtMs": 123,
        }
        profile = make_profile()

        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: (_ for _ in ()).throw(make_http_error(401)),
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNone(row["warning"])
        self.assertIn("鉴权接口连续异常", row["error"])
        self.assertEqual(
            row["_authIssueCount"], MODULE.DASHBOARD_AUTH_ERROR_GRACE_ATTEMPTS + 1
        )

    def test_first_403_keeps_previous_snapshot_as_warning(self) -> None:
        previous_row = make_previous_row()
        profile = make_profile()

        row = MODULE.build_dashboard_row_for_account(
            "alpha",
            profile,
            "alpha",
            lambda profile: (_ for _ in ()).throw(make_http_error(403)),
            lambda profile: [],
            previous=previous_row,
        )

        self.assertIsNone(row["error"])
        self.assertEqual(row["plan"], previous_row["plan"])
        self.assertEqual(row["windows"], previous_row["windows"])
        self.assertIn("鉴权接口临时波动", row["warning"])
        self.assertEqual(row["_authIssueStatus"], 403)
        self.assertEqual(row["_authIssueCount"], 1)

    def test_tolerated_warning_does_not_trigger_auto_switch(self) -> None:
        previous_row = make_previous_row()
        rows = [
            {
                **previous_row,
                "warning": "接口临时返回 401，已沿用上次额度数据",
                "isCurrent": True,
            },
            {
                "alias": "beta",
                "displayName": "Beta",
                "accountId": "acct_beta",
                "isCurrent": False,
                "plan": "plus",
                "windows": [
                    {"label": "5h", "usedPercent": 20.0, "resetAt": None},
                    {"label": "7d", "usedPercent": 10.0, "resetAt": None},
                ],
                "groups": [],
                "error": None,
                "warning": None,
            },
        ]

        decision = MODULE.build_auto_switch_decision(rows, current_alias="alpha")
        self.assertIsNone(decision)

    def test_auto_switch_skips_candidate_with_auth_warning(self) -> None:
        current_row = {
            **make_previous_row(),
            "windows": [
                {"label": "5h", "usedPercent": 98.0, "resetAt": None},
                {"label": "7d", "usedPercent": 10.0, "resetAt": None},
            ],
            "warning": None,
            "isCurrent": True,
        }
        warned_candidate = {
            "alias": "beta",
            "displayName": "Beta",
            "accountId": "acct_beta",
            "isCurrent": False,
            "plan": "plus",
            "windows": [
                {"label": "5h", "usedPercent": 10.0, "resetAt": None},
                {"label": "7d", "usedPercent": 10.0, "resetAt": None},
            ],
            "groups": [],
            "error": None,
            "warning": "接口临时返回 401，已沿用上次额度数据",
            "_authIssueCount": 1,
        }
        healthy_candidate = {
            "alias": "gamma",
            "displayName": "Gamma",
            "accountId": "acct_gamma",
            "isCurrent": False,
            "plan": "plus",
            "windows": [
                {"label": "5h", "usedPercent": 15.0, "resetAt": None},
                {"label": "7d", "usedPercent": 15.0, "resetAt": None},
            ],
            "groups": [],
            "error": None,
            "warning": None,
        }

        decision = MODULE.build_auto_switch_decision(
            [current_row, warned_candidate, healthy_candidate],
            current_alias="alpha",
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision["pickedAlias"], "gamma")

    def test_render_dashboard_text_shows_neutral_401_after_last_sync_and_keeps_data(
        self,
    ) -> None:
        row = {
            **make_previous_row(),
            "warning": "鉴权接口临时波动，已沿用上次额度数据，本次先不判定账号失效",
            "_authIssueStatus": 401,
            "_lastRefreshedAtMs": MODULE.current_time_ms(),
        }

        text = MODULE.render_dashboard_text([row], "alpha")

        self.assertIn("上次同步", text)
        self.assertIn("401 可能网络/鉴权", text)
        self.assertIn("5h", text)
        self.assertNotIn("沿用上次数据", text)

    def test_render_dashboard_text_shows_neutral_403_after_last_sync_and_keeps_data(
        self,
    ) -> None:
        row = {
            **make_previous_row(),
            "warning": "鉴权接口临时波动，已沿用上次额度数据，本次先不判定工作组异常",
            "_authIssueStatus": 403,
            "_lastRefreshedAtMs": MODULE.current_time_ms(),
        }

        text = MODULE.render_dashboard_text([row], "alpha")

        self.assertIn("上次同步", text)
        self.assertIn("403 可能网络/工作组", text)
        self.assertIn("5h", text)
        self.assertNotIn("沿用上次数据", text)

    def test_render_dashboard_text_shows_short_network_issue_after_last_sync(
        self,
    ) -> None:
        row = {
            **make_previous_row(),
            "warning": "网络连接失败，可能未开启 VPN/代理或当前节点不稳定；已保留上次数据",
            "_lastRefreshedAtMs": MODULE.current_time_ms(),
        }

        text = MODULE.render_dashboard_text([row], "alpha")

        self.assertIn("上次同步", text)
        self.assertIn("网络波动", text)
        self.assertIn("5h", text)
        self.assertNotIn("可能未开启", text)

    def test_render_dashboard_text_keeps_last_sync_on_second_line(self) -> None:
        row = {
            **make_previous_row(),
            "_lastRefreshedAtMs": MODULE.current_time_ms(),
        }

        text = MODULE.render_dashboard_text([row], "alpha", include_header=False)
        lines = text.splitlines()

        self.assertGreaterEqual(len(lines), 3)
        self.assertIn("账号ID", lines[0])
        self.assertNotIn("上次同步", lines[0])
        self.assertIn("上次同步", lines[1])

    def test_render_dashboard_text_keeps_sync_issue_on_second_line(self) -> None:
        row = {
            **make_previous_row(),
            "warning": "鉴权接口临时波动，已沿用上次额度数据，本次先不判定账号失效",
            "_authIssueStatus": 401,
            "_lastRefreshedAtMs": MODULE.current_time_ms(),
        }

        text = MODULE.render_dashboard_text([row], "alpha", include_header=False)
        lines = text.splitlines()

        self.assertGreaterEqual(len(lines), 3)
        self.assertNotIn("401 可能网络/鉴权", lines[0])
        self.assertIn("上次同步", lines[1])
        self.assertIn("401 可能网络/鉴权", lines[1])


if __name__ == "__main__":
    unittest.main()
