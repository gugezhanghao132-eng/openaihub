import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "package"
    / "app"
    / "openclaw_oauth_switcher.py"
)
SPEC = importlib.util.spec_from_file_location(
    "openclaw_oauth_switcher_strategy", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_store(
    root: Path, active: str, accounts: dict[str, dict[str, object]]
) -> None:
    payload = {
        "version": 1,
        "active": active,
        "accounts": accounts,
        "updatedAt": "2026-03-09T00:00:00+00:00",
    }
    (root / "openai-codex-accounts.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def make_account(alias: str) -> dict[str, object]:
    return {
        "type": "oauth",
        "provider": "openai-codex",
        "access": f"access-{alias}",
        "refresh": f"refresh-{alias}",
        "expires": MODULE.current_time_ms() + 86400 * 1000,
        "accountId": f"acct-{alias}",
        "displayName": alias,
    }


def make_previous_row(
    alias: str,
    *,
    is_current: bool,
    next_refresh_at_ms: int,
    remaining_5h: float,
    remaining_7d: float,
    reset_5h_ms: int,
    reset_7d_ms: int,
) -> dict[str, object]:
    today_key = MODULE.current_local_day_key()
    return {
        "alias": alias,
        "displayName": alias,
        "accountId": f"acct-{alias}",
        "isCurrent": is_current,
        "plan": "plus",
        "windows": [
            {
                "label": "5h",
                "usedPercent": 100.0 - remaining_5h,
                "resetAt": reset_5h_ms,
            },
            {
                "label": "7d",
                "usedPercent": 100.0 - remaining_7d,
                "resetAt": reset_7d_ms,
            },
        ],
        "groups": [{"accountId": f"acct-{alias}", "name": alias, "windows": []}],
        "error": None,
        "warning": None,
        "_lastRefreshedAtMs": MODULE.current_time_ms() - 1000,
        "_nextRefreshAtMs": next_refresh_at_ms,
        "_dailyRefreshAttemptDay": today_key,
        "_dailyRefreshAttemptAtMs": MODULE.current_time_ms() - 1000,
        "_dailyRefreshSuccessDay": today_key,
    }


class DashboardRefreshStrategyTests(unittest.TestCase):
    def test_only_current_and_one_daily_pending_background_account_refresh(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_store(
                root,
                "current",
                {
                    "current": make_account("current"),
                    "due": make_account("due"),
                    "cached": make_account("cached"),
                },
            )
            now_ms = MODULE.current_time_ms()
            previous_rows = [
                make_previous_row(
                    "current",
                    is_current=True,
                    next_refresh_at_ms=now_ms - 1,
                    remaining_5h=18.0,
                    remaining_7d=25.0,
                    reset_5h_ms=now_ms + 20 * 60 * 1000,
                    reset_7d_ms=now_ms + 2 * 86400 * 1000,
                ),
                make_previous_row(
                    "due",
                    is_current=False,
                    next_refresh_at_ms=now_ms - 1,
                    remaining_5h=12.0,
                    remaining_7d=18.0,
                    reset_5h_ms=now_ms + 25 * 60 * 1000,
                    reset_7d_ms=now_ms + 86400 * 1000,
                ),
                make_previous_row(
                    "cached",
                    is_current=False,
                    next_refresh_at_ms=now_ms + 30 * 60 * 1000,
                    remaining_5h=92.0,
                    remaining_7d=88.0,
                    reset_5h_ms=now_ms + 4 * 3600 * 1000,
                    reset_7d_ms=now_ms + 5 * 86400 * 1000,
                ),
            ]
            previous_rows[1]["_dailyRefreshSuccessDay"] = "2000-01-01"
            fetch_calls: list[str] = []

            def fetch_usage(profile: dict[str, object]) -> dict[str, object]:
                alias = str(profile.get("accountId") or "").removeprefix("acct-")
                fetch_calls.append(alias)
                return {
                    "plan": "plus",
                    "windows": [
                        {
                            "label": "5h",
                            "usedPercent": 40.0,
                            "resetAt": now_ms + 3600 * 1000,
                        },
                        {
                            "label": "7d",
                            "usedPercent": 35.0,
                            "resetAt": now_ms + 2 * 86400 * 1000,
                        },
                    ],
                }

            rows = MODULE.build_dashboard_rows(
                root=root,
                fetch_usage_fn=fetch_usage,
                fetch_catalog_fn=lambda profile: [],
                previous_rows=previous_rows,
            )

            self.assertEqual(fetch_calls, ["current", "due"])
            cached_row = next(row for row in rows if row["alias"] == "cached")
            self.assertEqual(cached_row["plan"], "plus")
            self.assertEqual(
                cached_row["_nextRefreshAtMs"], previous_rows[2]["_nextRefreshAtMs"]
            )

    def test_high_quota_background_row_skips_refresh_when_daily_done(self) -> None:
        now_ms = MODULE.current_time_ms()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_store(
                root,
                "current",
                {"current": make_account("current"), "cached": make_account("cached")},
            )
            previous_rows = [
                make_previous_row(
                    "current",
                    is_current=True,
                    next_refresh_at_ms=now_ms - 1,
                    remaining_5h=45.0,
                    remaining_7d=60.0,
                    reset_5h_ms=now_ms + 60 * 60 * 1000,
                    reset_7d_ms=now_ms + 2 * 86400 * 1000,
                ),
                make_previous_row(
                    "cached",
                    is_current=False,
                    next_refresh_at_ms=now_ms + 60 * 60 * 1000,
                    remaining_5h=95.0,
                    remaining_7d=90.0,
                    reset_5h_ms=now_ms + 4 * 3600 * 1000,
                    reset_7d_ms=now_ms + 5 * 86400 * 1000,
                ),
            ]
            fetch_calls: list[str] = []

            def fetch_usage(profile: dict[str, object]) -> dict[str, object]:
                alias = str(profile.get("accountId") or "").removeprefix("acct-")
                fetch_calls.append(alias)
                return {
                    "plan": "plus",
                    "windows": [
                        {
                            "label": "5h",
                            "usedPercent": 60.0,
                            "resetAt": now_ms + 3600 * 1000,
                        },
                        {
                            "label": "7d",
                            "usedPercent": 40.0,
                            "resetAt": now_ms + 2 * 86400 * 1000,
                        },
                    ],
                }

            MODULE.build_dashboard_rows(
                root=root,
                fetch_usage_fn=fetch_usage,
                fetch_catalog_fn=lambda profile: [],
                previous_rows=previous_rows,
            )

            self.assertEqual(fetch_calls, ["current"])

    def test_background_row_refreshes_when_7d_reset_within_one_day(self) -> None:
        now_ms = MODULE.current_time_ms()
        row = make_previous_row(
            "due-soon",
            is_current=False,
            next_refresh_at_ms=now_ms,
            remaining_5h=80.0,
            remaining_7d=80.0,
            reset_5h_ms=now_ms + 4 * 3600 * 1000,
            reset_7d_ms=now_ms + 12 * 3600 * 1000,
        )

        next_refresh_at_ms = MODULE.compute_dashboard_row_next_refresh_at(
            row, is_current=False, now_ms=now_ms
        )

        self.assertLessEqual(
            next_refresh_at_ms - now_ms, MODULE.AUTO_REFRESH_INTERVAL_MS
        )

    def test_background_row_refreshes_when_5h_remaining_below_50(self) -> None:
        now_ms = MODULE.current_time_ms()
        row = make_previous_row(
            "low-5h",
            is_current=False,
            next_refresh_at_ms=now_ms,
            remaining_5h=49.0,
            remaining_7d=90.0,
            reset_5h_ms=now_ms + 4 * 3600 * 1000,
            reset_7d_ms=now_ms + 5 * 86400 * 1000,
        )

        next_refresh_at_ms = MODULE.compute_dashboard_row_next_refresh_at(
            row, is_current=False, now_ms=now_ms
        )

        self.assertLessEqual(
            next_refresh_at_ms - now_ms, MODULE.AUTO_REFRESH_INTERVAL_MS
        )

    def test_daily_pending_row_respects_auth_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_store(
                root,
                "current",
                {
                    "current": make_account("current"),
                    "blocked": make_account("blocked"),
                },
            )
            now_ms = MODULE.current_time_ms()
            previous_rows = [
                make_previous_row(
                    "current",
                    is_current=True,
                    next_refresh_at_ms=now_ms - 1,
                    remaining_5h=40.0,
                    remaining_7d=60.0,
                    reset_5h_ms=now_ms + 60 * 60 * 1000,
                    reset_7d_ms=now_ms + 2 * 86400 * 1000,
                ),
                {
                    **make_previous_row(
                        "blocked",
                        is_current=False,
                        next_refresh_at_ms=now_ms - 1,
                        remaining_5h=20.0,
                        remaining_7d=20.0,
                        reset_5h_ms=now_ms + 30 * 60 * 1000,
                        reset_7d_ms=now_ms + 12 * 3600 * 1000,
                    ),
                    "_dailyRefreshSuccessDay": "2000-01-01",
                    "_authBlockedUntilMs": now_ms + 15 * 60 * 1000,
                    "_authBlockedRefresh": "refresh-blocked",
                },
            ]
            fetch_calls: list[str] = []

            def fetch_usage(profile: dict[str, object]) -> dict[str, object]:
                alias = str(profile.get("accountId") or "").removeprefix("acct-")
                fetch_calls.append(alias)
                return {
                    "plan": "plus",
                    "windows": [
                        {
                            "label": "5h",
                            "usedPercent": 40.0,
                            "resetAt": now_ms + 3600 * 1000,
                        },
                        {
                            "label": "7d",
                            "usedPercent": 35.0,
                            "resetAt": now_ms + 2 * 86400 * 1000,
                        },
                    ],
                }

            rows = MODULE.build_dashboard_rows(
                root=root,
                fetch_usage_fn=fetch_usage,
                fetch_catalog_fn=lambda profile: [],
                previous_rows=previous_rows,
            )

            self.assertEqual(fetch_calls, ["current"])
            blocked_row = next(row for row in rows if row["alias"] == "blocked")
            self.assertGreater(int(blocked_row.get("_authBlockedUntilMs") or 0), now_ms)


if __name__ == "__main__":
    unittest.main()
