from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

_ALLOWED_SCHEMES = {"http", "https", "s3"}


class AnalyzeRequest(BaseModel):
    # 支持公网 http/https URL，或 s3://bucket/key（私有桶，凭证由服务端 .env 配置）。
    # 用 str 而非 HttpUrl/AnyUrl：避免 pydantic 归一化/百分号编码破坏 S3 key 里的斜杠与特殊字符。
    url: str

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ValueError("url 必须以 http://、https:// 或 s3:// 开头")
        if not parsed.netloc:  # http(s) 的 host，或 s3 的 bucket
            raise ValueError("url 缺少主机名或存储桶名")
        return v
