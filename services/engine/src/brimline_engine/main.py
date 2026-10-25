"""HTTP entry point. Later milestones add scheduler, checker, and file-checker routes."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Brimline engine", version="0.0.0")


class Health(BaseModel):
    status: Literal["ok"]
    service: Literal["engine"]


@app.get("/health")
def health() -> Health:
    # The web app and CI use this to know the engine is up before calling it.
    return Health(status="ok", service="engine")
