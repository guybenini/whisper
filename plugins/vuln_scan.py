PLUGIN = {"name": "vuln_scan", "desc": "Local vulnerability scanner - missing patches, weak configs", "deps": [], "size": 3.5}

STUB_CODE = r"""
import ctypes, subprocess, os, platform

def _check_uac():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableLUA")
            if val == 0: return "UAC Disabled (vulnerable)"
            val2, _ = winreg.QueryValueEx(k, "ConsentPromptBehaviorAdmin")
            if val2 == 0: return "UAC No Prompt (vulnerable)"
            return "UAC Enabled (default)"
    except: return "UAC: Unknown"

def _check_defender():
    try:
        out = subprocess.check_output(["powershell", "-Command", "(Get-MpComputerStatus).RealTimeProtectionEnabled"], timeout=10, creationflags=0x08000000).decode().strip()
        if "True" in out: return "Defender: Enabled"
        return "Defender: DISABLED"
    except: return "Defender: Unknown"

def _check_firewall():
    try:
        out = subprocess.check_output(["netsh", "advfirewall", "show", "allprofiles", "state"], timeout=10, creationflags=0x08000000).decode()
        enabled = out.lower().count("on")
        total = out.lower().count("profile")
        if enabled >= total / 2: return f"Firewall: Enabled ({enabled}/{total} profiles)"
        return f"Firewall: WEAK ({enabled}/{total} profiles)"
    except: return "Firewall: Unknown"

def _check_lsa_protection():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\LSA", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "RunAsPPL")
            if val == 1: return "LSA Protection: Enabled (RunAsPPL)"
            return "LSA Protection: DISABLED"
    except: return "LSA Protection: Unknown"

def _check_credui():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableLUA")
            val2, _ = winreg.QueryValueEx(k, "EnableInstallerDetection")
            if val2 == 1: return "CredUI: Protected"
            return "CredUI: Weak"
    except: return "CredUI: Unknown"

def _check_powershell_logging():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "EnableScriptBlockLogging")
            if val == 1: return "PS Logging: Enabled"
            return "PS Logging: DISABLED"
    except: return "PS Logging: DISABLED"

def _check_wdigest():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "UseLogonCredential")
            if val != 0: return "WDigest: CLEARTEXT passwords"
            return "WDigest: Disabled"
    except: return "WDigest: Disabled"

def _check_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return "Privilege: ADMIN"
        return "Privilege: User"
    except: return "Privilege: Unknown"

def _cmd_vuln_scan(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] Vulnerability scanner requires Windows"}
        checks = [
            _check_admin(),
            _check_uac(),
            _check_defender(),
            _check_firewall(),
            _check_lsa_protection(),
            _check_credui(),
            _check_powershell_logging(),
            _check_wdigest(),
        ]
        vulns = [c for c in checks if "DISABLED" in c or "WEAK" in c or "CLEARTEXT" in c or "User" in c]
        output = "[+] Vulnerability Scan Results:\n"
        for c in checks:
            tag = "[!]" if ("DISABLED" in c or "WEAK" in c or "CLEARTEXT" in c) else "[+]" if "Enabled" in c or "ADMIN" in c else "[?]"
            output += f"  {tag} {c}\n"
        if vulns:
            output += f"\n  [!] {len(vulns)} potential vulnerabilities found\n"
        else:
            output += "\n  [OK] No obvious vulnerabilities\n"
        return {"output": output}
    except Exception as e: return {"output": f"[!] Vuln scan error: {e}"}
_CMDS["vuln_scan"] = _cmd_vuln_scan
"""

def get_commands():
    return {"vuln_scan": "_cmd_vuln_scan"}
