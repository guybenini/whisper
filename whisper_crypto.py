import os
import hmac
import hashlib
import json
import base64
import struct
import logging
from typing import Optional

log = logging.getLogger("whisper.crypto")

CIPHER_HMAC_STREAM = 0
CIPHER_AES_GCM = 1
CURRENT_CIPHER = CIPHER_AES_GCM
_has_aesgcm = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _has_aesgcm = True
    log.info("AES-GCM available (cryptography >= 3.0)")
except ImportError:
    CURRENT_CIPHER = CIPHER_HMAC_STREAM
    log.info("AES-GCM not available, using HMAC-SHA256 stream cipher")


def derive_key(password: str, salt: bytes, length: int = 32, iterations: int = 600000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, length)


def generate_salt(length: int = 16) -> bytes:
    return os.urandom(length)


# --- HMAC-SHA256 Stream Cipher (legacy, zero-dep) ---

def _encrypt_hmac_stream(plain: bytes, key: bytes) -> bytes:
    iv = os.urandom(16)
    ks, ctr = b"", 0
    while len(ks) < len(plain):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
        ctr += 1
    ct = bytes(p ^ k for p, k in zip(plain, ks))
    tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
    return iv + tag + ct


def _decrypt_hmac_stream(data: bytes, key: bytes) -> bytes:
    if len(data) < 32:
        raise ValueError("Data too short")
    iv, tag, ct = data[:16], data[16:32], data[32:]
    expected_tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Integrity check failed")
    ks, ctr = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest()
        ctr += 1
    return bytes(p ^ k for p, k in zip(ct, ks))


# --- AES-GCM Cipher (preferred) ---

def _encrypt_aesgcm(plain: bytes, key: bytes) -> bytes:
    if not _has_aesgcm:
        return _encrypt_hmac_stream(plain, key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plain, None)
    return nonce + ct


def _decrypt_aesgcm(data: bytes, key: bytes) -> bytes:
    if not _has_aesgcm:
        return _decrypt_hmac_stream(data, key)
    nonce, ct = data[:12], data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


# --- Unified API (version-tagged wire format) ---
# First byte is cipher version:
#   \x00 = HMAC-SHA256 stream cipher
#   \x01 = AES-GCM (12B nonce + AESGCM output)

def encrypt_bytes(plain: bytes, key: bytes, cipher_type: int = CURRENT_CIPHER) -> bytes:
    if cipher_type == CIPHER_AES_GCM:
        inner = _encrypt_aesgcm(plain, key)
        return bytes([CIPHER_AES_GCM]) + inner
    inner = _encrypt_hmac_stream(plain, key)
    return bytes([CIPHER_HMAC_STREAM]) + inner


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    if not data:
        raise ValueError("No data")
    cipher_type = data[0]
    inner = data[1:]
    if cipher_type == CIPHER_AES_GCM:
        return _decrypt_aesgcm(inner, key)
    elif cipher_type == CIPHER_HMAC_STREAM:
        return _decrypt_hmac_stream(inner, key)
    raise ValueError(f"Unknown cipher type: {cipher_type}")


def encrypt_dict(data: dict, key: bytes) -> str:
    return base64.b64encode(encrypt_bytes(json.dumps(data).encode(), key)).decode()


def decrypt_dict(data: str, key: bytes) -> dict:
    return json.loads(decrypt_bytes(base64.b64decode(data), key))
