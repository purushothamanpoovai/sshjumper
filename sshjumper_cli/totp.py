"""RFC 6238 TOTP (stdlib only) and otpauth:// URI parsing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}


@dataclass(frozen=True)
class TotpSpec:
    secret: bytes
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"

    def counter(self, at: float | None = None) -> int:
        return int((time.time() if at is None else at) // self.period)

    def remaining(self, at: float | None = None) -> float:
        now = time.time() if at is None else at
        return self.period - (now % self.period)

    def code(self, counter: int) -> str:
        digest = hmac.new(self.secret, struct.pack(">Q", counter), ALGORITHMS[self.algorithm]).digest()
        offset = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        return str(value % (10**self.digits)).zfill(self.digits)


def decode_base32(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").replace("-", "").upper()
    cleaned += "=" * (-len(cleaned) % 8)
    try:
        return base64.b32decode(cleaned)
    except (ValueError, TypeError) as exc:
        raise ValueError("TOTP secret is not valid base32") from exc


def parse_totp(value: str) -> TotpSpec:
    """Build a TotpSpec from a base32 secret or an ``otpauth://totp/...`` URI."""
    value = value.strip()
    if not value.lower().startswith("otpauth://"):
        return TotpSpec(secret=decode_base32(value))

    url = urlparse(value)
    if url.netloc.lower() != "totp":
        raise ValueError("only otpauth://totp URIs are supported")
    params = {k.lower(): unquote(v[0]) for k, v in parse_qs(url.query).items()}
    if "secret" not in params:
        raise ValueError("otpauth URI has no secret")
    algorithm = params.get("algorithm", "SHA1").upper()
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported TOTP algorithm: {algorithm}")
    return TotpSpec(
        secret=decode_base32(params["secret"]),
        digits=int(params.get("digits", 6)),
        period=int(params.get("period", 30)),
        algorithm=algorithm,
    )
