from __future__ import annotations

import asyncio
import ipaddress
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException

from model_analysis.core.config import (
    ALLOWED_EXTS,
    DOWNLOAD_DIR,
    MAX_DOWNLOAD_BYTES,
    S3_ACCESS_KEY,
    S3_ENDPOINT_URL,
    S3_REGION,
    S3_SECRET_KEY,
    S3_SESSION_TOKEN,
)

FAKE_IP_DNS_NET = ipaddress.ip_network("198.18.0.0/15")
S3_CHUNK_SIZE = 1024 * 1024

# botocore 可选：模块在无 boto3 时仍可导入（只走 http 路径 / 单测用 mock）。
try:
    from botocore.exceptions import BotoCoreError, ClientError

    _S3_ERRORS: tuple[type[Exception], ...] = (BotoCoreError, ClientError)
except ImportError:  # pragma: no cover - boto3 未安装时的兜底
    _S3_ERRORS = ()


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
    if urlparse(url).scheme.lower() == "s3":
        return await _download_s3(url)
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


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/key → (bucket, key)。

    手动 partition（不用 urlparse）：避免把 key 里的 ?/# 当 query/fragment，且保留内部斜杠。
    """
    rest = uri.split("://", 1)[1] if "://" in uri else ""
    bucket, _, key = rest.partition("/")
    if not bucket or not key or key.endswith("/"):
        raise _http_error(400, "S3_INVALID_URI", "S3 URI 格式应为 s3://bucket/key", uri)
    return bucket, key


def _build_s3_client():
    """按服务端 .env 凭证构造 boto3 S3 客户端；region/endpoint/session_token 仅在配置时传入。"""
    import boto3
    from botocore.client import Config

    kwargs = {
        "aws_access_key_id": S3_ACCESS_KEY,
        "aws_secret_access_key": S3_SECRET_KEY,
        "config": Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    }
    if S3_SESSION_TOKEN:
        kwargs["aws_session_token"] = S3_SESSION_TOKEN
    if S3_REGION:
        kwargs["region_name"] = S3_REGION
    if S3_ENDPOINT_URL:  # 仅 BOS/MinIO 等兼容存储
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


async def _download_s3(uri: str) -> tuple[Path, str]:
    """用服务端配置的 AK/SK 从私有 S3（或兼容存储）拉取对象。"""
    if not (S3_ACCESS_KEY and S3_SECRET_KEY):
        raise _http_error(400, "S3_NOT_CONFIGURED", "服务未配置 S3 凭证，无法从私有桶下载")

    bucket, key = _parse_s3_uri(uri)
    filename = Path(key).name  # basename，防路径穿越
    ext = _safe_ext(filename)  # 复用扩展名白名单校验，不支持格式在联网前就 fail-fast

    client = _build_s3_client()
    loop = asyncio.get_event_loop()

    try:
        obj = await loop.run_in_executor(None, lambda: client.get_object(Bucket=bucket, Key=key))
    except _S3_ERRORS as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") or exc.__class__.__name__
        raise _http_error(400, "S3_DOWNLOAD_FAILED", "S3 对象下载失败", f"{code}: {exc}") from exc

    # 大小防护 1：ContentLength 存在且超限即拒（不下载一个字节）。
    content_length = obj.get("ContentLength")
    body = obj["Body"]
    if content_length is not None and content_length > MAX_DOWNLOAD_BYTES:
        body.close()
        raise _http_error(400, "DOWNLOAD_TOO_LARGE", "远程文件过大，已拒绝下载")

    # 大小防护 2：流式写入时累计字节，兼容不报/谎报 ContentLength 的存储。
    local_path = DOWNLOAD_DIR / f"{uuid.uuid4()}{ext}"
    total = 0
    try:
        with local_path.open("wb") as file_obj:
            while True:
                chunk = await loop.run_in_executor(None, lambda: body.read(S3_CHUNK_SIZE))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    file_obj.close()
                    local_path.unlink(missing_ok=True)
                    raise _http_error(400, "DOWNLOAD_TOO_LARGE", "远程文件过大，已拒绝下载")
                file_obj.write(chunk)
    except _S3_ERRORS as exc:
        local_path.unlink(missing_ok=True)
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") or exc.__class__.__name__
        raise _http_error(400, "S3_DOWNLOAD_FAILED", "S3 对象下载失败", f"{code}: {exc}") from exc
    finally:
        body.close()

    return local_path, filename
