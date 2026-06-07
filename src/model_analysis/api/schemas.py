from pydantic import BaseModel, HttpUrl


class AnalyzeRequest(BaseModel):
    url: HttpUrl
