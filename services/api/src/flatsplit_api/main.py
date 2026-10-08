"""Local API wiring only; application endpoints belong in future issues."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="FlatSplit API", version="0.0.0")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["flatsplit-api"] = "flatsplit-api"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
