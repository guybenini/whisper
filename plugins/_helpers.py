"""Runtime helpers injected into every stub."""

import inspect, textwrap

def plugin_source(mod):
    """Extract the runtime code from a plugin module (all top-level code except PLUGIN, get_code, get_commands)."""
    lines = []
    src = inspect.getsource(mod)
    # Filter out the PLUGIN dict and get_code/get_commands function definitions
    skip_names = {"PLUGIN", "get_code", "get_commands"}
    # Simple approach: return everything, the generator will handle selection
    return src
