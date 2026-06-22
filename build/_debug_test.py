import sys, os, time, threading, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

port = 4451
engine = C2Engine(port=port)
engine.set_callback("status", lambda m: None)
t = threading.Thread(target=engine.start, daemon=True); t.start()
time.sleep(0.5)
print("running:", engine.running)

stub = generate_stub(sorted(PLUGIN_REGISTRY.keys()), "127.0.0.1", port, "whisper_secret_key", 1)
sp = os.path.join(os.path.dirname(__file__), "_test_stub.py")
with open(sp, "w") as f:
    f.write(stub)

ap = subprocess.Popen([sys.executable, sp], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print("Agent PID:", ap.pid)
print("Agent poll:", ap.poll())

time.sleep(3)
print("engine.clients:", len(engine.clients))
for cid, c in engine.clients.items():
    print(f"  Client {cid}: {c['info'].get('hostname')} alive={c['alive']}")
ap.kill()
engine.stop()
print("Done")
