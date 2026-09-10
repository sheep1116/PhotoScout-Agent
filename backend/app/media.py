"""Bounded image delivery by stored reference ID; never a general-purpose URL proxy."""
import asyncio
import ipaddress
import socket

import httpx

from .discovery import image_url

MAX_BYTES = 5 * 1024 * 1024


async def fetch_image(url):
    safe = image_url(url)
    if not safe:
        raise ValueError("IMAGE_SOURCE_NOT_ALLOWED")
    from urllib.parse import urlsplit
    host = urlsplit(safe).hostname
    async with asyncio.timeout(12):
        addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("IMAGE_ADDRESS_NOT_PUBLIC")
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", safe, headers={"User-Agent": "PhotoScout/0.2 reference-preview"}) as response:
                if response.status_code != 200:
                    raise ValueError("IMAGE_UNAVAILABLE")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise ValueError("IMAGE_TOO_LARGE")
                raw = bytes(content)
                kind = ("image/jpeg" if raw.startswith(b"\xff\xd8\xff") else
                        "image/png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else
                        "image/webp" if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP" else None)
                if not kind or response.headers.get("content-type", "").split(";")[0].lower() != kind:
                    raise ValueError("IMAGE_FORMAT_NOT_ALLOWED")
                return raw, kind
