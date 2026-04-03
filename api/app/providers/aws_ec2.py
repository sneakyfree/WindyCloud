"""AWS EC2 VPS provider — provisions and manages EC2 instances.

Implements the VPSProvider protocol. Uses boto3 for EC2 operations.
Start with AWS, migrate to own hardware when volume justifies it.
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from api.app.config import settings

# Plan definitions — maps plan IDs to EC2 instance types
PLANS = {
    "starter": {
        "name": "Starter",
        "instance_type": "t3.micro",
        "vcpus": 2,
        "ram_gb": 1,
        "disk_gb": 20,
        "bandwidth_tb": 1.0,
        "price_cents_per_month": 500,  # $5/mo
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "basic": {
        "name": "Basic",
        "instance_type": "t3.small",
        "vcpus": 2,
        "ram_gb": 2,
        "disk_gb": 40,
        "bandwidth_tb": 2.0,
        "price_cents_per_month": 1000,  # $10/mo
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "standard": {
        "name": "Standard",
        "instance_type": "t3.medium",
        "vcpus": 2,
        "ram_gb": 4,
        "disk_gb": 80,
        "bandwidth_tb": 3.0,
        "price_cents_per_month": 2000,  # $20/mo
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "performance": {
        "name": "Performance",
        "instance_type": "t3.large",
        "vcpus": 2,
        "ram_gb": 8,
        "disk_gb": 160,
        "bandwidth_tb": 4.0,
        "price_cents_per_month": 4000,  # $40/mo
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
    "pro": {
        "name": "Pro",
        "instance_type": "t3.xlarge",
        "vcpus": 4,
        "ram_gb": 16,
        "disk_gb": 320,
        "bandwidth_tb": 5.0,
        "price_cents_per_month": 8000,  # $80/mo
        "regions": ["us-east-1", "us-west-2", "eu-west-1"],
    },
}

# AMI mappings per region (Ubuntu 24.04)
DEFAULT_AMIS = {
    "us-east-1": "ami-0c7217cdde317cfec",
    "us-west-2": "ami-03f65b8614a860c29",
    "eu-west-1": "ami-0905a3c97561e0b69",
}


class AWSEC2Provider:
    """AWS EC2 VPS provider — implements the VPSProvider protocol."""

    def __init__(self) -> None:
        self._ec2 = boto3.client(
            "ec2",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    def _resolve_ami(self, image: str, region: str) -> str:
        """Resolve image name to AMI ID."""
        if image.startswith("ami-"):
            return image
        return DEFAULT_AMIS.get(region, DEFAULT_AMIS["us-east-1"])

    async def create(
        self,
        identity_id: str,
        plan: str,
        region: str,
        image: str,
        hostname: str | None = None,
    ) -> dict[str, Any]:
        plan_config = PLANS.get(plan)
        if not plan_config:
            raise ValueError(f"Unknown plan: {plan}")

        ami_id = self._resolve_ami(image, region)
        instance_type = plan_config["instance_type"]

        try:
            resp = self._ec2.run_instances(
                ImageId=ami_id,
                InstanceType=instance_type,
                MinCount=1,
                MaxCount=1,
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": hostname or f"windy-{identity_id[:8]}"},
                            {"Key": "windy-identity-id", "Value": identity_id},
                            {"Key": "windy-plan", "Value": plan},
                            {"Key": "windy-managed", "Value": "true"},
                        ],
                    }
                ],
            )
            instance = resp["Instances"][0]
            return {
                "provider_instance_id": instance["InstanceId"],
                "status": "provisioning",
                "ip_address": instance.get("PublicIpAddress"),
            }
        except ClientError as e:
            raise RuntimeError(f"EC2 launch failed: {e}")

    async def get(self, provider_instance_id: str) -> dict[str, Any]:
        try:
            resp = self._ec2.describe_instances(InstanceIds=[provider_instance_id])
            instance = resp["Reservations"][0]["Instances"][0]
            ec2_state = instance["State"]["Name"]
            status_map = {
                "pending": "provisioning",
                "running": "running",
                "stopping": "stopped",
                "stopped": "stopped",
                "shutting-down": "terminated",
                "terminated": "terminated",
            }
            return {
                "status": status_map.get(ec2_state, ec2_state),
                "ip_address": instance.get("PublicIpAddress"),
            }
        except ClientError:
            return {"status": "unknown", "ip_address": None}

    async def action(self, provider_instance_id: str, action: str) -> dict[str, str]:
        try:
            if action == "start":
                self._ec2.start_instances(InstanceIds=[provider_instance_id])
                return {"status": "starting", "message": "Server starting"}
            elif action == "stop":
                self._ec2.stop_instances(InstanceIds=[provider_instance_id])
                return {"status": "stopping", "message": "Server stopping"}
            elif action == "reboot":
                self._ec2.reboot_instances(InstanceIds=[provider_instance_id])
                return {"status": "rebooting", "message": "Server rebooting"}
            else:
                raise ValueError(f"Unknown action: {action}")
        except ClientError as e:
            raise RuntimeError(f"EC2 action failed: {e}")

    async def delete(self, provider_instance_id: str) -> bool:
        try:
            self._ec2.terminate_instances(InstanceIds=[provider_instance_id])
            return True
        except ClientError:
            return False

    def plans(self) -> list[dict[str, Any]]:
        return [
            {"plan_id": pid, **{k: v for k, v in p.items() if k != "instance_type"}}
            for pid, p in PLANS.items()
        ]

    async def health(self) -> bool:
        if not settings.aws_access_key_id:
            return False
        try:
            self._ec2.describe_regions(RegionNames=[settings.aws_region])
            return True
        except ClientError:
            return False
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Unexpected EC2 health check error")
            return False
