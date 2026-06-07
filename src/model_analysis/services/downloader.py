from __future__ import annotations

import ipaddress
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException

from model_analysis.core.config import ALLOWED_EXTS, DOWNLOAD_DIR, MAX_DOWNLOAD_BYTES

FAKE_IP_DNS_NET = ipaddress.ip_network("198.18.0.0/15")


def _error(code: str, message: str, detail: str | None = None) -> dict:
    return {"code": code, "message": message, "detail": detail or message}


def _http_error(status_code: int, code: str, message: str, detail: str | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_error(code, message, detail))


def _filename_from_response(url: str, headers: httpx.Headers) -> str:
    disposition = headers.get("content-disposition", "")
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].split(";", 1)[0].strip().strip('"')
        if filename:
            return Path(unquote(filename)).name

    parsed = urlparse(url)
    filename = Path(unquote(parsed.path)).name
    return filename or "remote_model.glb"


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower() or ".glb"
    if ext not in ALLOWED_EXTS:
        raise _http_error(400, "UNSUPPORTED_FORMAT", f"不支持的模型格式: {ext}")
    return ext


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _http_error(400, "INVALID_URL", "URL 必须是 http 或 https 地址")

    try:
        hostname_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        hostname_ip = None

    if hostname_ip:
        if not hostname_ip.is_global:
            raise _http_error(400, "URL_NOT_PUBLIC", "不允许下载本机或内网地址")
        return

    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise _http_error(400, "URL_DNS_FAILED", "URL 域名无法解析", str(exc)) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip in FAKE_IP_DNS_NET:
            continue
        if not ip.is_global:
            raise _http_error(400, "URL_NOT_PUBLIC", "不允许下载本机或内网地址", str(ip))


async def download_model(url: str) -> tuple[Path, str]:
    _validate_public_url(url)
    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        try:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise _http_error(400, "DOWNLOAD_HTTP_ERROR", f"URL 下载失败: HTTP {response.status_code}")

                filename = _filename_from_response(url, response.headers)
                ext = _safe_ext(filename)
                local_path = DOWNLOAD_DIR / f"{uuid.uuid4()}{ext}"
                total = 0

                with local_path.open("wb") as file_obj:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            file_obj.close()
                            local_path.unlink(missing_ok=True)
                            raise _http_error(400, "DOWNLOAD_TOO_LARGE", "远程文件过大，已拒绝下载")
                        file_obj.write(chunk)

                return local_path, filename
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise _http_error(400, "DOWNLOAD_FAILED", "URL 下载失败", str(exc)) from exc
