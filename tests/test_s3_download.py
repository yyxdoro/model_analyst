from __future__ import annotations

import asyncio

import pytest
from botocore.exceptions import ClientError
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
    """store: {bucket: bytes}；缺桶时 get_object 抛 NoSuchKey，模拟候选桶未命中。"""

    def __init__(self, store: dict[str, bytes], content_length_override=None):
        self.store = store
        self.content_length_override = content_length_override
        self.calls: list[tuple[str, str]] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 (boto3 kwargs 命名)
        self.calls.append((Bucket, Key))
        if Bucket not in self.store:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "no"}}, "GetObject")
        data = self.store[Bucket]
        cl = self.content_length_override if self.content_length_override is not None else len(data)
        return {"ContentLength": cl, "Body": FakeBody(data)}


def _aws_on(monkeypatch, buckets):
    monkeypatch.setattr(downloader, "S3_ACCESS_KEY", "AK", raising=False)
    monkeypatch.setattr(downloader, "S3_SECRET_KEY", "SK", raising=False)
    monkeypatch.setattr(downloader, "S3_BUCKETS", buckets, raising=False)


def _bos_on(monkeypatch, buckets):
    monkeypatch.setattr(downloader, "BOS_ACCESS_KEY", "BAK", raising=False)
    monkeypatch.setattr(downloader, "BOS_SECRET_KEY", "BSK", raising=False)
    monkeypatch.setattr(downloader, "BOS_ENDPOINT", "https://bos.example.com", raising=False)
    monkeypatch.setattr(downloader, "BOS_BUCKETS", buckets, raising=False)


def _all_off(monkeypatch):
    for name in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "BOS_ACCESS_KEY", "BOS_SECRET_KEY", "BOS_ENDPOINT"):
        monkeypatch.setattr(downloader, name, "", raising=False)


# ── _parse_s3_uri ──


def test_parse_s3_uri_preserves_inner_slashes():
    assert downloader._parse_s3_uri("s3://bkt/a/b/c.glb") == ("bkt", "a/b/c.glb")


@pytest.mark.parametrize("uri", ["s3://bkt", "s3://bkt/", "s3:///key.glb"])
def test_parse_s3_uri_rejects_bad_shape(uri):
    with pytest.raises(HTTPException) as exc:
        downloader._parse_s3_uri(uri)
    assert exc.value.detail["code"] == "S3_INVALID_URI"


# ── 显式 s3://bucket/key：按桶名路由到 AWS / BOS ──


def test_explicit_bos_bucket_uses_bos_client(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["tripo-data"])
    _bos_on(monkeypatch, ["cn-openapi"])
    aws = FakeClient({})
    bos = FakeClient({"cn-openapi": b"BOSDATA"})
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: aws)
    monkeypatch.setattr(downloader, "_build_bos_client", lambda: bos)

    path, name = asyncio.run(downloader._download_s3_object("cn-openapi", "tcli_x/20260721/uuid"))

    assert name == "uuid"
    assert path.read_bytes() == b"BOSDATA"
    assert bos.calls == [("cn-openapi", "tcli_x/20260721/uuid")]
    assert aws.calls == []  # 没走 AWS


def test_explicit_aws_bucket_uses_aws_client(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["tripo-data"])
    _bos_on(monkeypatch, ["cn-openapi"])
    aws = FakeClient({"tripo-data": b"AWSDATA"})
    bos = FakeClient({})
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: aws)
    monkeypatch.setattr(downloader, "_build_bos_client", lambda: bos)

    path, name = asyncio.run(downloader._download_s3_object("tripo-data", "foo.glb"))

    assert path.read_bytes() == b"AWSDATA"
    assert aws.calls == [("tripo-data", "foo.glb")]
    assert bos.calls == []


def test_explicit_bos_bucket_without_bos_creds(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["tripo-data"])
    _all_off(monkeypatch)  # 关掉 BOS（和 AWS）
    _aws_on(monkeypatch, ["tripo-data"])  # 只留 AWS
    monkeypatch.setattr(downloader, "BOS_BUCKETS", ["cn-openapi"], raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3_object("cn-openapi", "k"))
    assert exc.value.detail["code"] == "S3_NOT_CONFIGURED"


# ── 裸 key：候选桶逐个试 ──


def test_bare_key_not_configured(monkeypatch):
    _all_off(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_bare_key("foo.glb"))
    assert exc.value.detail["code"] == "S3_NOT_CONFIGURED"


def test_bare_key_iterates_then_hits_second_bucket(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["b1", "b2"])
    _all_off(monkeypatch)
    _aws_on(monkeypatch, ["b1", "b2"])  # 仅 AWS
    client = FakeClient({"b2": b"HIT"})
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: client)

    path, name = asyncio.run(downloader._download_bare_key("foo.glb"))

    assert name == "foo.glb"
    assert path.read_bytes() == b"HIT"
    assert client.calls == [("b1", "foo.glb"), ("b2", "foo.glb")]  # b1 未命中→b2


def test_bare_key_falls_through_aws_to_bos(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["a1"])
    _bos_on(monkeypatch, ["c1"])
    aws = FakeClient({})  # AWS 全未命中
    bos = FakeClient({"c1": b"BOSHIT"})
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: aws)
    monkeypatch.setattr(downloader, "_build_bos_client", lambda: bos)

    path, name = asyncio.run(downloader._download_bare_key("k.glb"))

    assert path.read_bytes() == b"BOSHIT"
    assert aws.calls == [("a1", "k.glb")]
    assert bos.calls == [("c1", "k.glb")]


def test_bare_key_none_found(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["a1"])
    _bos_on(monkeypatch, ["c1"])
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: FakeClient({}))
    monkeypatch.setattr(downloader, "_build_bos_client", lambda: FakeClient({}))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_bare_key("missing.glb"))
    assert exc.value.detail["code"] == "S3_KEY_NOT_FOUND"


# ── 大小 / 扩展名 ──


def test_too_large_via_content_length(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(downloader, "MAX_DOWNLOAD_BYTES", 10, raising=False)
    _aws_on(monkeypatch, ["b1"])
    _all_off(monkeypatch)
    _aws_on(monkeypatch, ["b1"])
    client = FakeClient({"b1": b"x" * 100}, content_length_override=100)
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3_object("b1", "big.glb"))
    assert exc.value.detail["code"] == "DOWNLOAD_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []  # 没落盘


def test_too_large_via_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(downloader, "MAX_DOWNLOAD_BYTES", 10, raising=False)
    _aws_on(monkeypatch, ["b1"])
    _all_off(monkeypatch)
    _aws_on(monkeypatch, ["b1"])
    client = FakeClient({"b1": b"x" * 100}, content_length_override=None)  # 不报 ContentLength
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_s3_object("b1", "big.glb"))
    assert exc.value.detail["code"] == "DOWNLOAD_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []  # 半成品已删


def test_unsupported_ext_fail_fast(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["b1"])
    _all_off(monkeypatch)
    _aws_on(monkeypatch, ["b1"])
    client = FakeClient({"b1": b"data"})
    monkeypatch.setattr(downloader, "_build_aws_client", lambda: client)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(downloader._download_bare_key("readme.txt"))
    assert exc.value.detail["code"] == "UNSUPPORTED_FORMAT"
    assert client.calls == []  # 联网前就 fail-fast


def test_key_without_ext_defaults_glb(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", tmp_path, raising=False)
    _aws_on(monkeypatch, ["b1"])
    _bos_on(monkeypatch, ["cn-openapi"])
    bos = FakeClient({"cn-openapi": b"MODEL"})
    monkeypatch.setattr(downloader, "_build_bos_client", lambda: bos)

    # 你的真实例子：cn-openapi + 无扩展名 key
    path, name = asyncio.run(
        downloader._download_s3_object("cn-openapi", "tcli_f5dd/20260721/2fb24398-b5e7-4a00")
    )
    assert path.suffix == ".glb"  # 无扩展名 → 默认 .glb
    assert path.read_bytes() == b"MODEL"
