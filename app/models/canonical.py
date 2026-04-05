"""Canonical data model — platform-agnostic resource representations."""

from enum import Enum

from pydantic import Field

from app.models.common import BaseResource


class ComputeType(str, Enum):
    """Classification of compute resources."""

    VM = "vm"
    BAREMETAL = "baremetal"
    CONTAINER = "container"


class StorageType(str, Enum):
    """Classification of storage volumes."""

    BLOCK = "block"
    FILE = "file"
    OBJECT = "object"


class NetworkType(str, Enum):
    """Classification of network segments."""

    VLAN = "vlan"
    VSWITCH = "vswitch"
    NSX_SEGMENT = "nsx_segment"
    SUBNET = "subnet"
    VPC = "vpc"


class ProtocolType(str, Enum):
    """Supported network protocols for security policies."""

    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ALL = "all"


class ComputeResource(BaseResource):
    """A compute workload — VM, bare-metal server, or container."""

    type: ComputeType = Field(description="Kind of compute resource")
    cpu: int = Field(gt=0, description="Number of vCPUs")
    memory_gb: int = Field(gt=0, description="Memory in gigabytes")
    os: str = Field(description="Operating system (e.g. ubuntu-22.04)")
    storage_gb: int = Field(default=0, ge=0, description="Root disk size in GB")
    ip_addresses: list[str] = Field(
        default_factory=list, description="Assigned IP addresses"
    )


class NetworkSegment(BaseResource):
    """A network construct — VLAN, vSwitch, NSX segment, or subnet."""

    type: NetworkType = Field(description="Kind of network segment")
    cidr: str = Field(description="CIDR block (e.g. 10.0.1.0/24)")
    gateway: str = Field(default="", description="Gateway IP address")
    vlan_id: int | None = Field(default=None, description="VLAN identifier if applicable")
    connectivity: list[str] = Field(
        default_factory=list,
        description="IDs or names of connected network segments",
    )


class SecurityPolicy(BaseResource):
    """A firewall or security group rule."""

    source: str = Field(description="Source CIDR or resource reference")
    destination: str = Field(description="Destination CIDR or resource reference")
    port: int | None = Field(default=None, ge=0, le=65535, description="Port number")
    port_range: str = Field(default="", description="Port range (e.g. 8080-8090)")
    protocol: ProtocolType = Field(description="Network protocol")
    action: str = Field(default="allow", description="allow or deny")
    direction: str = Field(default="inbound", description="inbound or outbound")


class StorageVolume(BaseResource):
    """A storage volume attached to a compute resource."""

    type: StorageType = Field(description="Kind of storage")
    size_gb: int = Field(gt=0, description="Volume size in gigabytes")
    iops: int | None = Field(default=None, description="Provisioned IOPS if applicable")
    attached_to: str = Field(
        default="", description="ID of the compute resource this is attached to"
    )


class KubernetesResource(BaseResource):
    """A Kubernetes workload or configuration object."""

    kind: str = Field(description="K8s resource kind (Deployment, Service, etc.)")
    namespace: str = Field(default="default", description="Kubernetes namespace")
    spec: dict = Field(default_factory=dict, description="Resource spec as raw dict")
    replicas: int | None = Field(default=None, description="Desired replica count")
