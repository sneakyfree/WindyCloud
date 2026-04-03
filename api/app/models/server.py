"""Pydantic models for VPS server API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ServerPlan(BaseModel):
    plan_id: str
    name: str
    vcpus: int
    ram_gb: int
    disk_gb: int
    bandwidth_tb: float
    price_cents_per_month: int
    regions: list[str]


class PlansResponse(BaseModel):
    plans: list[ServerPlan]


class ServerInstance(BaseModel):
    server_id: str
    identity_id: str
    plan_id: str
    region: str
    image: str
    status: str  # provisioning, running, stopped, terminated
    ip_address: str | None = None
    hostname: str | None = None
    created_at: datetime
    monthly_cost_cents: int


class ServerCreateRequest(BaseModel):
    plan: str
    region: str = "us-east-1"
    image: str = "ubuntu-24-04"
    hostname: str | None = None


class ServerCreateResponse(BaseModel):
    server_id: str
    status: str
    message: str = "Server provisioning started"


class ServerActionRequest(BaseModel):
    action: str  # start, stop, reboot


class ActionResult(BaseModel):
    server_id: str
    action: str
    status: str
    message: str


class ServerListResponse(BaseModel):
    servers: list[ServerInstance]
    total: int


class ServerDeleteResponse(BaseModel):
    server_id: str
    deleted: bool
    message: str = "Server terminated"
