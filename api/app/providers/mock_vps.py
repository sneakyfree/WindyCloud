"""Mock VPS provider that stores server state in the database."""

from __future__ import annotations

import uuid

# Plan definitions matching aws_ec2.py structure
MOCK_PLANS: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "vcpus": 1,
        "ram_gb": 1,
        "disk_gb": 25,
        "bandwidth_tb": 1.0,
        "price_cents_per_month": 500,
        "instance_type": "mock.small",
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "basic": {
        "name": "Basic",
        "vcpus": 2,
        "ram_gb": 2,
        "disk_gb": 50,
        "bandwidth_tb": 2.0,
        "price_cents_per_month": 1000,
        "instance_type": "mock.medium",
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "standard": {
        "name": "Standard",
        "vcpus": 2,
        "ram_gb": 4,
        "disk_gb": 80,
        "bandwidth_tb": 3.0,
        "price_cents_per_month": 2000,
        "instance_type": "mock.large",
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "performance": {
        "name": "Performance",
        "vcpus": 4,
        "ram_gb": 8,
        "disk_gb": 160,
        "bandwidth_tb": 4.0,
        "price_cents_per_month": 4000,
        "instance_type": "mock.xlarge",
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "pro": {
        "name": "Pro",
        "vcpus": 8,
        "ram_gb": 16,
        "disk_gb": 320,
        "bandwidth_tb": 5.0,
        "price_cents_per_month": 8000,
        "instance_type": "mock.2xlarge",
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
}


class MockVPSProvider:
    """Mock VPS provider — no real infrastructure, just state tracking."""

    async def create(
        self,
        identity_id: str,
        plan: str,
        region: str = "us-east-1",
        image: str = "ubuntu-24-04",
        hostname: str | None = None,
        user_data: str | None = None,
    ) -> dict:
        if plan not in MOCK_PLANS:
            raise ValueError(f"Unknown plan: {plan}")

        return {
            "provider_instance_id": f"mock-{uuid.uuid4().hex[:12]}",
            "status": "running",
            "ip_address": "192.168.1.100",
        }

    async def get(self, instance_id: str) -> dict:
        return {
            "status": "running",
            "ip_address": "192.168.1.100",
        }

    async def action(self, instance_id: str, action: str) -> dict:
        status_map = {"start": "running", "stop": "stopped", "reboot": "running"}
        new_status = status_map.get(action, "unknown")
        return {
            "status": new_status,
            "message": f"Server {action} completed",
        }

    async def delete(self, instance_id: str) -> dict:
        return {"deleted": True}

    async def plans(self) -> dict:
        return MOCK_PLANS
