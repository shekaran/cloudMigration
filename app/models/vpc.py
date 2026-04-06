"""IBM Cloud VPC target resource models."""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class VPCResource(BaseModel):
    """Base for all VPC target resources."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="VPC resource name")
    resource_group: str = Field(default="default", description="IBM Cloud resource group")
    region: str = Field(default="us-south", description="IBM Cloud region")


class VPCNetwork(VPCResource):
    """An IBM Cloud VPC network."""

    address_prefix_cidr: str = Field(description="VPC address prefix CIDR")


class VPCSubnet(VPCResource):
    """An IBM Cloud VPC subnet."""

    vpc_id: UUID = Field(description="Parent VPC ID")
    zone: str = Field(default="us-south-1", description="Availability zone")
    ipv4_cidr_block: str = Field(description="Subnet CIDR block")
    public_gateway: bool = Field(default=False, description="Attach public gateway")
    source_network_name: str = Field(default="", description="Original source network name")


class VPCSecurityGroup(VPCResource):
    """An IBM Cloud VPC security group."""

    vpc_id: UUID = Field(description="Parent VPC ID")
    rules: list["VPCSecurityGroupRule"] = Field(default_factory=list)


class VPCSecurityGroupRule(BaseModel):
    """A single rule within a VPC security group."""

    direction: str = Field(description="inbound or outbound")
    protocol: str = Field(description="tcp, udp, icmp, or all")
    port_min: int | None = Field(default=None)
    port_max: int | None = Field(default=None)
    remote_cidr: str = Field(default="0.0.0.0/0", description="Source/destination CIDR")


class VPCInstance(VPCResource):
    """An IBM Cloud VPC Virtual Server Instance."""

    vpc_id: UUID = Field(description="Parent VPC ID")
    subnet_id: UUID = Field(description="Subnet to place the instance in")
    profile: str = Field(description="Instance profile (e.g. bx2-4x16)")
    image: str = Field(description="OS image name")
    zone: str = Field(default="us-south-1", description="Availability zone")
    boot_volume_gb: int = Field(default=100, description="Boot volume size in GB")
    data_volumes: list[int] = Field(default_factory=list, description="Data volume sizes in GB")
    security_group_ids: list[UUID] = Field(default_factory=list)
    source_vm_name: str = Field(default="", description="Original source VM name")


class VPCTranslationResult(BaseModel):
    """Complete translation output — all VPC resources to be provisioned."""

    vpc: VPCNetwork
    subnets: list[VPCSubnet] = Field(default_factory=list)
    security_groups: list[VPCSecurityGroup] = Field(default_factory=list)
    instances: list[VPCInstance] = Field(default_factory=list)

    @property
    def resource_count(self) -> int:
        return 1 + len(self.subnets) + len(self.security_groups) + len(self.instances)
