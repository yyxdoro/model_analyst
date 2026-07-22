from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException

from model_analysis.core.config import (
    ALLOWED_EXTS,
    BOS_ACCESS_KEY,
    BOS_BUCKETS,
    BOS_ENDPOINT,
    BOS_SECRET_KEY,
    DOWNLOAD_DIR,
    MAX_DOWNLOAD_BYTES,
    S3_ACCESS_KEY,
    S3_BUCKETS,
    S3_REGION,
    S3_SECRET_KEY,
    S3_SESSION_TOKEN,
)

logger = logging.getLogger(__name__)

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
    """按 scheme 分派：http(s) 走公网下载；s3://bucket/key 或裸 key 走对象存储（AWS/BOS）。"""
    url = url.strip()
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return await _download_http(url)
    if scheme == "s3":
        bucket, key = _parse_s3_uri(url)
        return await _download_s3_object(bucket, key)
    # 无 scheme：裸 object key → 在候选桶里逐个查
    return await _download_bare_key(url)


async def _download_http(url: str) -> tuple[Path, str]:
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


# ── 对象存储（AWS S3 / 百度 BOS）───────────────────────────────


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/key → (bucket, key)。

    手动 partition（不用 urlparse）：避免把 key 里的 ?/# 当 query/fragment，且保留内部斜杠。
    """
    rest = uri.split("://", 1)[1] if "://" in uri else ""
    bucket, _, key = rest.partition("/")
    if not bucket or not key or key.endswith("/"):
        raise _http_error(400, "S3_INVALID_URI", "S3 URI 格式应为 s3://bucket/key", uri)
    return bucket, key


def _aws_configured() -> bool:
    return bool(S3_ACCESS_KEY and S3_SECRET_KEY)


def _bos_configured() -> bool:
    return bool(BOS_ACCESS_KEY and BOS_SECRET_KEY and BOS_ENDPOINT)


def _build_aws_client():
    """AWS S3 客户端（region 定位）。"""
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
    return boto3.client("s3", **kwargs)


def _build_bos_client():
    """百度 BOS 客户端（S3 兼容，独立 endpoint）。"""
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=BOS_ENDPOINT,
        aws_access_key_id=BOS_ACCESS_KEY,
        aws_secret_access_key=BOS_SECRET_KEY,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _backends() -> list[tuple[str, "callable", list[str]]]:
    """已配置的后端：(名字, client 工厂, 候选桶)。AWS 在前，BOS 在后。"""
    out: list[tuple[str, "callable", list[str]]] = []
    if _aws_configured():
        out.append(("aws", _build_aws_client, S3_BUCKETS))
    if _bos_configured():
        out.append(("bos", _build_bos_client, BOS_BUCKETS))
    return out


def _client_for_bucket(bucket: str):
    """按桶名归属选后端凭证：桶在 BOS_BUCKETS → BOS；在 S3_BUCKETS → AWS；未知桶优先 AWS。"""
    if bucket in BOS_BUCKETS:
        if not _bos_configured():
            raise _http_error(400, "S3_NOT_CONFIGURED", "未配置 BOS 凭证（BOS_ACCESS_KEY/BOS_SECRET_KEY/BOS_ENDPOINT）")
        return _build_bos_client()
    if bucket in S3_BUCKETS:
        if not _aws_configured():
            raise _http_error(400, "S3_NOT_CONFIGURED", "未配置 AWS 凭证（S3_ACCESS_KEY/S3_SECRET_KEY）")
        return _build_aws_client()
    # 未知桶：优先 AWS，其次 BOS
    if _aws_configured():
        return _build_aws_client()
    if _bos_configured():
        return _build_bos_client()
    raise _http_error(400, "S3_NOT_CONFIGURED", "服务未配置任何 S3/BOS 凭证")


async def _save_stream_to_disk(body, content_length, ext: str) -> Path:
    """把 get_object 的流写盘，双重大小防护（ContentLength + 流式累计）。结束时关闭 body。"""
    if content_length is not None and content_length > MAX_DOWNLOAD_BYTES:
        body.close()
        raise _http_error(400, "DOWNLOAD_TOO_LARGE", "远程文件过大，已拒绝下载")

    local_path = DOWNLOAD_DIR / f"{uuid.uuid4()}{ext}"
    total = 0
    loop = asyncio.get_event_loop()
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
    return local_path


async def _download_s3_object(bucket: str, key: str) -> tuple[Path, str]:
    """显式 s3://bucket/key：按桶名选后端凭证，直接下载；失败即报错。"""
    ext = _safe_ext(Path(key).name)  # key 无扩展名时默认 .glb
    client = _client_for_bucket(bucket)
    loop = asyncio.get_event_loop()
    try:
        obj = await loop.run_in_executor(None, lambda: client.get_object(Bucket=bucket, Key=key))
    except _S3_ERRORS as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") or exc.__class__.__name__
        raise _http_error(400, "S3_DOWNLOAD_FAILED", "S3 对象下载失败", f"{code}: {exc}") from exc
    local_path = await _save_stream_to_disk(obj["Body"], obj.get("ContentLength"), ext)
    return local_path, Path(key).name


async def _download_bare_key(key: str) -> tuple[Path, str]:
    """裸 object key（无桶名）：在所有已配置后端的候选桶里逐个 get_object，首个命中即用。"""
    backends = _backends()
    if not backends:
        raise _http_error(400, "S3_NOT_CONFIGURED", "服务未配置任何 S3/BOS 凭证，无法用裸 key 下载")
    ext = _safe_ext(Path(key).name)  # 联网前 fail-fast
    loop = asyncio.get_event_loop()
    tried: list[str] = []
    for name, factory, buckets in backends:
        client = factory()
        for bucket in buckets:
            tried.append(f"{name}:{bucket}")
            try:
                obj = await loop.run_in_executor(None, lambda b=bucket: client.get_object(Bucket=b, Key=key))
            except _S3_ERRORS as exc:
                logger.debug("get_object 未命中 [%s://%s/%s]: %s", name, bucket, key, exc)
                continue
            logger.info("命中候选桶 [%s://%s/%s]", name, bucket, key)
            local_path = await _save_stream_to_disk(obj["Body"], obj.get("ContentLength"), ext)
            return local_path, Path(key).name
    raise _http_error(400, "S3_KEY_NOT_FOUND", f"候选桶均无此对象: {key}", f"tried={tried}")
