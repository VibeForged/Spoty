# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['aiosqlite']
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('cogs')


a = Analysis(
    ['E:\\__PROJECTS__\\__PROGRAMMING__\\PERSONAL\\__BOTS__\\__DISCORD__\\Spoty_Discord_Bot\\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('E:\\__PROJECTS__\\__PROGRAMMING__\\PERSONAL\\__BOTS__\\__DISCORD__\\Spoty_Discord_Bot\\.env.example', '.'), ('E:\\__PROJECTS__\\__PROGRAMMING__\\PERSONAL\\__BOTS__\\__DISCORD__\\Spoty_Discord_Bot\\LavaLink', 'Lavalink'), ('E:\\__PROJECTS__\\__PROGRAMMING__\\PERSONAL\\__BOTS__\\__DISCORD__\\Spoty_Discord_Bot\\alembic', 'alembic')],
    hiddenimports=hiddenimports,
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
    name='SpotyDiscordBot',
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
    name='SpotyDiscordBot',
)
