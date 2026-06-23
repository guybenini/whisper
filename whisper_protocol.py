import json
import struct
from typing import Any, Optional, Callable

MAX_MESSAGE_SIZE = 262144


def encode_frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


def decode_frame_header(header: bytes) -> int:
    return struct.unpack(">I", header)[0]


def recv_exact(recv_fn: Callable[[int], bytes], size: int) -> Optional[bytes]:
    data = b""
    while len(data) < size:
        chunk = recv_fn(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def recv_frame(recv_fn: Callable[[int], bytes]) -> Optional[bytes]:
    header = recv_exact(recv_fn, 4)
    if header is None:
        return None
    size = decode_frame_header(header)
    if size < 1 or size > MAX_MESSAGE_SIZE:
        return None
    return recv_exact(recv_fn, size)


def send_frame(send_fn: Callable[[bytes], int], payload: bytes) -> bool:
    try:
        frame = encode_frame(payload)
        send_fn(frame)
        return True
    except Exception:
        return False


def validate_message(msg: Any) -> Optional[str]:
    if not isinstance(msg, dict):
        return "Message must be a dict"
    if "type" not in msg:
        return "Message missing 'type' field"
    cmd_type = msg["type"]
    if not isinstance(cmd_type, str) or len(cmd_type) > 64:
        return "Invalid 'type' field"
    for key in msg:
        if not isinstance(key, str) or len(key) > 128:
            return f"Invalid key: {key}"
    return None
