import importlib.util
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
    "openclaw_oauth_switcher_login", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LoginHelperRuntimeTests(unittest.TestCase):
    def test_build_login_helper_env_points_to_bundled_runtime_login_module(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "login.json"

            env = MODULE.build_login_helper_env(output_path)

        expected_entry = (
            MODULE.SCRIPT_DIR / "bundled_runtime" / "oauth" / "openai-codex.js"
        )
        self.assertTrue(expected_entry.exists())
        self.assertEqual(env.get("OPENCLAW_LOGIN_MODULE_ENTRY"), str(expected_entry))

    def test_login_helper_available_requires_real_login_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            helper_path = Path(tmp_dir) / "openai_codex_login_helper.mjs"
            helper_path.write_text("export {};\n", encoding="utf-8")
            fake_node = Path(tmp_dir) / "node.exe"
            fake_node.write_text("", encoding="utf-8")
            missing_module = Path(tmp_dir) / "missing-openai-codex.js"

            original_node = MODULE.BUNDLED_NODE_EXE
            original_runtime_dir = MODULE.BUNDLED_RUNTIME_DIR
            original_runtime_candidates = MODULE.BUNDLED_RUNTIME_DIR_CANDIDATES
            original_module_entry = MODULE.BUNDLED_OPENAI_CODEX_HELPER_ENTRY
            original_which = MODULE.shutil.which
            original_appdata = MODULE.os.environ.get("APPDATA")
            try:
                setattr(MODULE, "BUNDLED_NODE_EXE", fake_node)
                setattr(
                    MODULE, "BUNDLED_RUNTIME_DIR", Path(tmp_dir) / "missing-runtime"
                )
                setattr(
                    MODULE,
                    "BUNDLED_RUNTIME_DIR_CANDIDATES",
                    [Path(tmp_dir) / "missing-runtime"],
                )
                setattr(MODULE, "BUNDLED_OPENAI_CODEX_HELPER_ENTRY", missing_module)
                MODULE.shutil.which = lambda _: None
                MODULE.os.environ["APPDATA"] = str(Path(tmp_dir) / "missing-appdata")

                self.assertFalse(MODULE.login_helper_available(helper_path))
            finally:
                setattr(MODULE, "BUNDLED_NODE_EXE", original_node)
                setattr(MODULE, "BUNDLED_RUNTIME_DIR", original_runtime_dir)
                setattr(
                    MODULE,
                    "BUNDLED_RUNTIME_DIR_CANDIDATES",
                    original_runtime_candidates,
                )
                setattr(
                    MODULE, "BUNDLED_OPENAI_CODEX_HELPER_ENTRY", original_module_entry
                )
                MODULE.shutil.which = original_which
                if original_appdata is None:
                    MODULE.os.environ.pop("APPDATA", None)
                else:
                    MODULE.os.environ["APPDATA"] = original_appdata

    def test_resolve_login_module_entry_falls_back_to_legacy_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            preferred_runtime = Path(tmp_dir) / "bundled_runtime"
            legacy_runtime = Path(tmp_dir) / "runtime"
            legacy_entry = legacy_runtime / "oauth" / "openai-codex.js"
            legacy_entry.parent.mkdir(parents=True, exist_ok=True)
            legacy_entry.write_text("export {};\n", encoding="utf-8")

            original_runtime_dir = MODULE.BUNDLED_RUNTIME_DIR
            original_runtime_candidates = MODULE.BUNDLED_RUNTIME_DIR_CANDIDATES
            original_module_entry = MODULE.BUNDLED_OPENAI_CODEX_HELPER_ENTRY
            original_appdata = MODULE.os.environ.get("APPDATA")
            try:
                setattr(MODULE, "BUNDLED_RUNTIME_DIR", preferred_runtime)
                setattr(
                    MODULE,
                    "BUNDLED_RUNTIME_DIR_CANDIDATES",
                    [preferred_runtime, legacy_runtime],
                )
                setattr(
                    MODULE,
                    "BUNDLED_OPENAI_CODEX_HELPER_ENTRY",
                    preferred_runtime / "oauth" / "openai-codex.js",
                )
                MODULE.os.environ["APPDATA"] = str(Path(tmp_dir) / "missing-appdata")

                self.assertEqual(MODULE.resolve_login_module_entry(), legacy_entry)
            finally:
                setattr(MODULE, "BUNDLED_RUNTIME_DIR", original_runtime_dir)
                setattr(
                    MODULE,
                    "BUNDLED_RUNTIME_DIR_CANDIDATES",
                    original_runtime_candidates,
                )
                setattr(
                    MODULE, "BUNDLED_OPENAI_CODEX_HELPER_ENTRY", original_module_entry
                )
                if original_appdata is None:
                    MODULE.os.environ.pop("APPDATA", None)
                else:
                    MODULE.os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
