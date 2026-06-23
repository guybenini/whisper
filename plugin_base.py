"""Plugin interface protocol and validation for Whisper C2."""
from __future__ import annotations
import typing as t
from typing import Protocol, runtime_checkable


class PluginInfo(t.TypedDict, total=False):
    name: str
    desc: str
    deps: list[str]
    size: float


@runtime_checkable
class PluginModule(Protocol):
    PLUGIN: PluginInfo
    STUB_CODE: str
    def get_commands(self) -> dict[str, str]: ...


def validate_plugin_module(mod: object, name: str) -> bool:
    if not hasattr(mod, "PLUGIN"):
        raise TypeError(f"Plugin '{name}' missing PLUGIN dict")
    if not isinstance(mod.PLUGIN, dict):
        raise TypeError(f"Plugin '{name}': PLUGIN must be a dict, got {type(mod.PLUGIN).__name__}")
    for key in ("name", "desc"):
        if key not in mod.PLUGIN:
            raise KeyError(f"Plugin '{name}': PLUGIN missing required key '{key}'")
    if not hasattr(mod, "STUB_CODE"):
        raise TypeError(f"Plugin '{name}' missing STUB_CODE")
    if not isinstance(mod.STUB_CODE, str):
        raise TypeError(f"Plugin '{name}': STUB_CODE must be a str, got {type(mod.STUB_CODE).__name__}")
    if not mod.STUB_CODE.strip():
        raise ValueError(f"Plugin '{name}': STUB_CODE is empty")
    if not hasattr(mod, "get_commands"):
        raise TypeError(f"Plugin '{name}' missing get_commands()")
    if not callable(mod.get_commands):
        raise TypeError(f"Plugin '{name}': get_commands must be callable")
    cmds = mod.get_commands()
    if not isinstance(cmds, dict):
        raise TypeError(f"Plugin '{name}': get_commands() must return dict, got {type(cmds).__name__}")
    for cmd_name, func_name in cmds.items():
        if not isinstance(cmd_name, str):
            raise TypeError(f"Plugin '{name}': command name must be str, got {type(cmd_name).__name__}")
        if not isinstance(func_name, str):
            raise TypeError(f"Plugin '{name}': command '{cmd_name}' function ref must be str, got {type(func_name).__name__}")
        if func_name not in mod.STUB_CODE:
            raise ValueError(f"Plugin '{name}': command '{cmd_name}' maps to '{func_name}' but not found in STUB_CODE")
    return True
