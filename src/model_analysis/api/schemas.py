from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class AnalyzeRequest(BaseModel):
    # 支持公网 http/https URL、s3://bucket/key（私有桶，凭证由服务端 .env 配置），
    # 或裸 object key（无 scheme，服务端在候选桶里查）。
    # 用 str 而非 HttpUrl/AnyUrl：避免 pydantic 归一化/百分号编码破坏 S3 key 里的斜杠与特殊字符。
    url: str

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url 不能为空")
        parsed = urlparse(v)
        scheme = parsed.scheme.lower()
        if scheme in {"http", "https", "s3"}:
            if not parsed.netloc:
                raise ValueError("url 缺少主机名或存储桶名")
        elif scheme:
            raise ValueError("url 必须是 http://、https://、s3://bucket/key 或裸对象 key")
        # scheme == "" → 裸 object key，交给服务端在候选桶里查
        return v
