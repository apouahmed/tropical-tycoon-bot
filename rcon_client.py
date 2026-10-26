"""Minimal Minecraft RCON client (Source RCON). Optional — staff tools degrade when unset."""

from __future__ import annotations

import os
import socket
import struct
from dataclasses import dataclass


class RconError(RuntimeError):
    pass


@dataclass(frozen=True)
class RconConfig:
    host: str
    port: int
    password: str

    @staticmethod
    def from_env() -> RconConfig | None:
        host = (os.getenv("RCON_HOST") or "").strip()
        password = (os.getenv("RCON_PASSWORD") or "").strip()
        if not host or not password:
            return None
        port_raw = (os.getenv("RCON_PORT") or "25575").strip()
        try:
            port = int(port_raw)
        except ValueError as e:
            raise RconError(f"RCON_PORT is invalid: {port_raw}") from e
        return RconConfig(host=host, port=port, password=password)


def _pack(request_id: int, req_type: int, payload: str) -> bytes:
    body = payload.encode("utf-8") + b"\x00\x00"
    size = 4 + 4 + len(body)
    return struct.pack("<iii", size, request_id, req_type) + body


def _recv_packet(sock: socket.socket) -> tuple[int, int, str]:
    header = _recv_exact(sock, 12)
    size, req_id, req_type = struct.unpack("<iii", header)
    remaining = size - 8
    if remaining < 2:
        raise RconError("RCON packet too short")
    payload = _recv_exact(sock, remaining)
    text = payload[:-2].decode("utf-8", errors="replace")
    return req_id, req_type, text


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RconError("RCON connection closed")
        buf.extend(chunk)
    return bytes(buf)


def execute(command: str, config: RconConfig | None = None, timeout: float = 8.0) -> str:
    """Run one console command. Returns the server response text (may be empty)."""
    cfg = config or RconConfig.from_env()
    if cfg is None:
        raise RconError("RCON is not configured (set RCON_HOST and RCON_PASSWORD)")
    if not command or not command.strip():
        raise RconError("Command is empty")
    cmd = command.strip()
    if cmd.startswith("/"):
        cmd = cmd[1:]

    with socket.create_connection((cfg.host, cfg.port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(_pack(1, 3, cfg.password))
        auth_id, _, _ = _recv_packet(sock)
        if auth_id == -1:
            raise RconError("RCON authentication failed")
        sock.sendall(_pack(2, 2, cmd))
        _, _, body = _recv_packet(sock)
        return body.strip()
