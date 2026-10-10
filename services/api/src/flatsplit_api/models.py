"""Public response models shared by every API handler."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["flatsplit-api"] = "flatsplit-api"
