# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPEC).resolve().parent


a = Analysis(
    [str(ROOT / 'package' / 'app' / 'openai_launcher.py')],
    pathex=[str(ROOT / 'package' / 'app')],
    binaries=[],
    datas=[
        (str(ROOT / 'package' / 'app' / 'openai_codex_login_helper.mjs'), '.'),
        (str(ROOT / 'package' / 'app' / 'openclaw_restart_gateway.ps1'), '.'),
        (str(ROOT / 'package' / 'app' / 'openclaw_restart_gateway.sh'), '.'),
        (str(ROOT / 'package' / 'app' / 'bundled_runtime'), 'bundled_runtime'),
    ],
    hiddenimports=[
        'openclaw_oauth_switcher',
        'requests',
        'rich',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='openaihub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='openaihub',
)
