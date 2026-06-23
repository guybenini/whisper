import os
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_config.json")


@dataclass
class WhisperConfig:
    # C2 server
    c2_host: str = "0.0.0.0"
    c2_port: int = 4443
    c2_password: str = ""
    c2_salt_hex: str = ""

    # Builder defaults
    builder_default_host: str = "127.0.0.1"
    builder_default_port: int = 4443
    builder_default_delay: int = 10

    # Web server
    web_port: int = 8080
    web_host: str = "0.0.0.0"

    # Crypto
    pbkdf2_iterations: int = 600000
    key_length: int = 32

    # Network
    reconnect_delay: int = 10
    socket_timeout: int = 30
    listen_backlog: int = 10

    # Logging
    log_level: str = "DEBUG"
    log_dir: str = ""

    def __post_init__(self) -> None:
        if not self.c2_password:
            self.c2_password = os.environ.get("WHISPER_PASSWORD", "")
        if not self.c2_salt_hex:
            self.c2_salt_hex = os.environ.get("WHISPER_SALT_HEX", "")
        if not self.log_dir:
            self.log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        if not self.c2_salt_hex:
            import secrets
            self.c2_salt_hex = secrets.token_hex(16)


def load_config(path: Optional[str] = None) -> WhisperConfig:
    p = path or CONFIG_FILE
    cfg = WhisperConfig()
    if os.path.exists(p):
        try:
            with open(p, "r") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception:
            pass
    return cfg


def save_config(cfg: WhisperConfig, path: Optional[str] = None) -> None:
    p = path or CONFIG_FILE
    d = asdict(cfg)
    d.pop("c2_password", None)
    d.pop("c2_salt_hex", None)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(d, f, indent=2, default=str)
