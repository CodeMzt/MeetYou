# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


repo_root = Path(SPECPATH).parents[1]
uiautomation_bin = repo_root / ".venv" / "Lib" / "site-packages" / "uiautomation" / "bin"
uiautomation_binaries = [
    (str(path), "uiautomation/bin")
    for path in uiautomation_bin.glob("UIAutomationClient_VC140_*.dll")
]

a = Analysis(
    [str(repo_root / "desktop_client" / "main.py")],
    pathex=[str(repo_root)],
    binaries=uiautomation_binaries,
    datas=[(str(repo_root / "desktop_client" / "build_info.json"), "desktop_client")],
    hiddenimports=[
        "aiohttp",
        "platform_layer.windows",
        "platform_layer.macos",
        "platform_layer.linux",
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
    name="desktop_client",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name="desktop_client",
)
