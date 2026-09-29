"""Modbus client: RTU-over-TCP (Robustel Transparent) and standard Modbus TCP.

Field-verified behaviour (v23.9):
  * ELGAS/ELCORplus and ABB speak raw RTU frames behind the Robustel Transparent
    TCP server: Slave | 0x03 | Addr Hi/Lo | Qty Hi/Lo | CRC Lo/Hi.
  * CRC16 Modbus: poly 0xA001, init 0xFFFF.

Desync protection
-----------------
In v23.9, when one field timed out, the device's late reply stayed in the socket
and the next field read that stale reply as its own value (the CRC was valid, so
nothing caught it). This client:
  1. Marks the socket "dirty" after any error and reconnects before the next request.
  2. Drains leftover bytes from the socket before every request.
  3. Checks the reply's byte count against the requested register count.
"""
from __future__ import annotations

import select
import socket
import struct
from typing import Optional


class ModbusError(Exception):
    """Error of a single request (exception reply, CRC, unexpected reply)."""


class ModbusExceptionResponse(ModbusError):
    """The device returned a complete, valid Modbus exception reply (e.g. 0x02:
    illegal data address). No bytes are left in the socket, the connection is
    healthy and does not need to be re-opened. (Reconnecting here made a single
    mistyped register double the traffic of a 100 MB/month production line.)"""


class ModbusTransportError(ModbusError):
    """Connection lost / timeout. The next request may retry after reconnecting."""


class ModbusConnectError(ModbusTransportError):
    """The TCP connection could not be established: the device is unreachable this cycle."""


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def build_rtu_read_request(slave: int, address: int, quantity: int) -> bytes:
    body = struct.pack(">BBHH", slave & 0xFF, 0x03, address & 0xFFFF, quantity & 0xFFFF)
    return body + crc16_modbus(body).to_bytes(2, "little")


# Measured TCP/IP overhead, used to estimate the IP traffic the carrier bills
# (tcpdump, Linux with TCP timestamps, Robustel emulated with RS232 latency):
#   one request/reply round: payload + ~172 bytes (request, reply, two ACK segments)
#   one connect + close:     ~340 bytes (SYN, SYN-ACK, ACK, FIN/ACK x2)
REQUEST_OVERHEAD_BYTES = 172
CONNECT_OVERHEAD_BYTES = 340


class ModbusClient:
    """One TCP connection to one physical device. Not thread-safe; every device
    uses its own client in its own thread.

    The connection is KEPT OPEN between cycles (persistent connection): a TCP
    handshake every 10 s on a mobile line added ~25% traffic for ELGAS and ~140%
    for ABB. It is re-opened only after an error or when the peer closes it."""

    def __init__(self, host: str, port: int, slave: int, timeout: float, transport: str = "rtu_over_tcp"):
        if transport not in ("rtu_over_tcp", "modbus_tcp"):
            raise ValueError(f"Unsupported transport: {transport}")
        self.host = host
        self.port = port
        self.slave = slave
        self.timeout = timeout
        self.transport = transport
        self._sock: Optional[socket.socket] = None
        self._dirty = False
        self._tid = 0
        # traffic counters (for the data usage estimate)
        self.connects = 0
        self.requests = 0
        self.payload_bytes = 0

    @property
    def is_connected(self) -> bool:
        return self._sock is not None and not self._dirty

    def estimated_ip_bytes(self) -> int:
        return (self.payload_bytes + self.requests * REQUEST_OVERHEAD_BYTES
                + self.connects * CONNECT_OVERHEAD_BYTES)

    # -- connection management ---------------------------------------------
    def connect(self) -> None:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise ModbusConnectError(f"Cannot connect to {self.host}:{self.port}: {exc}") from exc
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._dirty = False
        self.connects += 1

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def __enter__(self) -> "ModbusClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _drain(self) -> bool:
        """Discard bytes waiting in the socket (late replies). Returns False if
        the peer has closed the connection (modem reboot, idle timeout, ...)."""
        assert self._sock is not None
        while True:
            try:
                readable, _, _ = select.select([self._sock], [], [], 0)
            except (OSError, ValueError):
                return False
            if not readable:
                return True
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                return False
            if not chunk:
                return False

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
            except socket.timeout as exc:
                raise ModbusTransportError("Reply timed out") from exc
            except OSError as exc:
                raise ModbusTransportError(f"Read error: {exc}") from exc
            if not chunk:
                raise ModbusTransportError("Connection closed while receiving the reply")
            buf.extend(chunk)
        return bytes(buf)

    # -- reading -----------------------------------------------------------
    def read_holding_registers(self, address: int, quantity: int) -> list[int]:
        """Function 03. `address` is the 0-based raw (wire) address."""
        if not 1 <= quantity <= 125:
            raise ValueError(f"Invalid register count: {quantity}")
        if self._sock is None or self._dirty:
            self.connect()
        elif not self._drain():
            # The persistent connection was closed by the peer: reconnect transparently.
            self.connect()
        self.requests += 1
        rtu = self.transport == "rtu_over_tcp"
        self.payload_bytes += 8 if rtu else 12
        try:
            registers = self._read_rtu(address, quantity) if rtu else self._read_tcp(address, quantity)
            self.payload_bytes += (5 if rtu else 9) + 2 * quantity
            return registers
        except ModbusExceptionResponse:
            self.payload_bytes += 5 if rtu else 9
            raise
        except ModbusError:
            # Leftovers of this request may remain in the socket: reconnect before the next one.
            self._dirty = True
            raise
        except OSError as exc:
            self._dirty = True
            raise ModbusTransportError(f"Socket error: {exc}") from exc

    def _read_rtu(self, address: int, quantity: int) -> list[int]:
        assert self._sock is not None
        self._sock.sendall(build_rtu_read_request(self.slave, address, quantity))
        head = self._recv_exact(3)
        slave, function, third = head
        if slave != (self.slave & 0xFF):
            raise ModbusError(f"Unexpected slave {slave} (expected {self.slave})")
        if function & 0x80:
            frame = head + self._recv_exact(2)
            if int.from_bytes(frame[-2:], "little") != crc16_modbus(frame[:-2]):
                raise ModbusError("CRC error in exception reply")
            raise ModbusExceptionResponse(f"Modbus exception 0x{third:02X} (address {address})")
        if function != 0x03:
            raise ModbusError(f"Unexpected function 0x{function:02X}")
        if third != quantity * 2:
            raise ModbusError(f"Unexpected byte count {third} (expected {quantity * 2})")
        frame = head + self._recv_exact(third + 2)
        got = int.from_bytes(frame[-2:], "little")
        calc = crc16_modbus(frame[:-2])
        if got != calc:
            raise ModbusError(f"CRC mismatch: received 0x{got:04X}, calculated 0x{calc:04X}")
        return list(struct.unpack(f">{quantity}H", frame[3:-2]))

    def _read_tcp(self, address: int, quantity: int) -> list[int]:
        assert self._sock is not None
        self._tid = (self._tid % 0xFFFF) + 1
        pdu = struct.pack(">BHH", 0x03, address & 0xFFFF, quantity & 0xFFFF)
        mbap = struct.pack(">HHHB", self._tid, 0, 1 + len(pdu), self.slave & 0xFF)
        self._sock.sendall(mbap + pdu)
        tid, proto, length, unit = struct.unpack(">HHHB", self._recv_exact(7))
        if tid != self._tid:
            raise ModbusError(f"Unexpected transaction id {tid} (expected {self._tid})")
        if proto != 0 or length < 3:
            raise ModbusError(f"Invalid MBAP header (proto={proto}, length={length})")
        if unit != (self.slave & 0xFF):
            raise ModbusError(f"Unexpected unit id {unit}")
        body = self._recv_exact(length - 1)
        function = body[0]
        if function & 0x80:
            raise ModbusExceptionResponse(f"Modbus exception 0x{body[1]:02X} (address {address})")
        if function != 0x03 or body[1] != quantity * 2 or len(body) != 2 + quantity * 2:
            raise ModbusError("Unexpected Modbus TCP reply")
        return list(struct.unpack(f">{quantity}H", body[2:]))
