from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class UnsafeURLError(ValueError):
    pass


def assert_safe_url(url: str, *, resolve_dns: bool = True) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("missing host")
    if host.lower() in {"localhost"}:
        raise UnsafeURLError("localhost blocked")

    # Literal IP in URL
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        _reject_private(ip)
        return

    if not resolve_dns:
        return

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS failed for {host}") from exc
    for info in infos:
        addr = info[4][0]
        _reject_private(ipaddress.ip_address(addr))


def _reject_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    for net in PRIVATE_NETWORKS:
        if ip in net:
            raise UnsafeURLError(f"private/blocked address: {ip}")
