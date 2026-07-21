from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from model_analysis.services import downloader


class FakeBody:
    """模拟 botocore StreamingBody：read(amt) 分块吐字节，读完返回 b""。"""

    def __init__(self, data: bytes, chunk: int = 1024):
        self._buf = data
        self._chunk = chunk
        self.closed = False

    def read(self, amt: int | None = None) -> bytes:
        n = amt if amt is not None else self._chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, data: bytes, content_length):
        self._data = data
        self._content_length = content_length
        self.get_object_called = False

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 (boto3 kwargs 命名)
        self.get_object_called = True
        obj = {"Body": FakeBody(self._data)}
        if self._content_length is not None:
            obj["ContentLength"] = self._content_length
        return obj


def _configure_creds(monkeypatch):
    monkeypatch.setattr(downloader, "S3_ACCESS_KEY", "AK", raising=False)
    monkeypatch.setattr(downloader, "S3_SECRET_KEY", "SK", raising=False)


def _inject_client(monkeypatch, client):
    monkeypatch.setattr(downloader, "_build_s3_client", lambda: client)
    return client


def test_parse_s3_uri_preserves_inner_slashes():
    assert downloader._parse_s3_uri("s3://bkt/a/b/c.glb") == ("bkt", "a/b/c.glb")


@pytest.mark.parametrize("uri", ["s3://bkt", "s3://bkt/", "s3:///key.glb"])
def test_parse_s3_uri_rejects_bad_shape(uri):
    with pytest.raises(HTTPException) as exc:
        downloader._parse_s3_uri(uri)
    assert exc.value.detail["code"] == "S3_INVALID_URI"


def test_download_s3_not_configured(monkeypatch):
    monkeypatch.setattr(downloader, "S3_ACCESS_KEY", "", raising=False)
    monkeypatch.setattr(downloader, "S3_SECRET_KEY", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3("s3://b/k.glb"))
    assert exc.value.detail["code"] == "S3_NOT_CONFIGURED"


def test_download_s3_happy_path(monkeypatch, tmp_path):
    _configure_creds(monkeypatch)
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    data = b"GLB-BYTES" * 100
    client = _inject_client(monkeypatch, FakeClient(data, content_length=len(data)))

    local_path, filename = asyncio.run(downloader._download_s3("s3://bkt/models/foo.glb"))

    assert filename == "foo.glb"
    assert local_path.parent == tmp_path
    assert local_path.suffix == ".glb"
    assert local_path.read_bytes() == data
    assert client.get_object_called is True


def test_download_s3_too_large_via_content_length(monkeypatch, tmp_path):
    _configure_creds(monkeypatch)
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(downloader, "MAX_DOWNLOAD_BYTES", 10, raising=False)
    body = FakeBody(b"x" * 100)
    client = FakeClient(b"x" * 100, content_length=100)
    # 直接观测 body 未被读取：注入一个已知 body 的 client
    client.get_object = lambda Bucket, Key: {"ContentLength": 100, "Body": body}  # noqa: N803
    _inject_client(monkeypatch, client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3("s3://bkt/big.glb"))
    assert exc.value.detail["code"] == "DOWNLOAD_TOO_LARGE"
    assert body.closed is True
    assert list(tmp_path.iterdir()) == []  # 没有落盘


def test_download_s3_too_large_via_stream(monkeypatch, tmp_path):
    _configure_creds(monkeypatch)
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(downloader, "MAX_DOWNLOAD_BYTES", 10, raising=False)
    # ContentLength 缺失，靠流式累计触发超限
    _inject_client(monkeypatch, FakeClient(b"x" * 100, content_length=None))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3("s3://bkt/big.glb"))
    assert exc.value.detail["code"] == "DOWNLOAD_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []  # 半成品文件已删


def test_download_s3_unsupported_ext(monkeypatch, tmp_path):
    _configure_creds(monkeypatch)
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    client = _inject_client(monkeypatch, FakeClient(b"data", content_length=4))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3("s3://bkt/readme.txt"))
    assert exc.value.detail["code"] == "UNSUPPORTED_FORMAT"
    assert client.get_object_called is False  # 联网前 fail-fast
