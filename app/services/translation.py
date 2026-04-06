"""Translation service — converts canonical model to IBM VPC target model."""

import structlog

from app.models.canonical import ComputeResource, NetworkSegment, SecurityPolicy
from app.models.responses import DiscoveredResources
from app.models.vpc import (
    VPCInstance,
    VPCNetwork,
    VPCSecurityGroup,
    VPCSecurityGroupRule,
    VPCSubnet,
    VPCTranslationResult,
)

logger = structlog.get_logger(__name__)

# Mapping from source OS identifiers to IBM Cloud VPC image names
OS_IMAGE_MAP: dict[str, str] = {
    "ubuntu": "ibm-ubuntu-22-04-4-minimal-amd64-1",
    "centos": "ibm-centos-stream-9-amd64-2",
    "rhel": "ibm-redhat-8-8-minimal-amd64-2",
    "windows": "ibm-windows-server-2022-full-standard-amd64-3",
}

# Mapping from (cpu, memory_gb) to IBM Cloud VPC instance profiles
PROFILE_MAP: list[tuple[int, int, str]] = [
    (2, 8, "bx2-2x8"),
    (4, 8, "bx2-4x8"),
    (4, 16, "bx2-4x16"),
    (8, 16, "bx2-8x16"),
    (8, 32, "bx2-8x32"),
    (16, 32, "bx2-16x32"),
    (16, 64, "bx2-16x64"),
    (32, 128, "bx2-32x128"),
    (64, 256, "bx2-64x256"),
]


class TranslationService:
    """Translates canonical DiscoveredResources into IBM VPC target resources."""

    def __init__(self, vpc_name: str = "migration-vpc", region: str = "us-south") -> None:
        self._vpc_name = vpc_name
        self._region = region

    def translate(self, canonical: DiscoveredResources) -> VPCTranslationResult:
        """Convert canonical resources to a complete VPC translation result.

        Args:
            canonical: Normalized resources from discovery.

        Returns:
            VPCTranslationResult with VPC, subnets, security groups, and instances.
        """
        logger.info("translation_started", resource_count=canonical.resource_count)

        vpc = self._create_vpc(canonical)
        subnets = self._translate_networks(canonical.networks, vpc.id)
        security_groups = self._translate_security_policies(
            canonical.security_policies, vpc.id
        )
        instances = self._translate_compute(
            canonical.compute, canonical.storage, vpc.id, subnets, security_groups
        )

        result = VPCTranslationResult(
            vpc=vpc,
            subnets=subnets,
            security_groups=security_groups,
            instances=instances,
        )
        logger.info(
            "translation_completed",
            vpc=vpc.name,
            subnets=len(subnets),
            security_groups=len(security_groups),
            instances=len(instances),
        )
        return result

    def _create_vpc(self, canonical: DiscoveredResources) -> VPCNetwork:
        """Create the target VPC resource."""
        # Use the first network's CIDR as address prefix, or a default
        if canonical.networks:
            prefix = canonical.networks[0].cidr
        else:
            prefix = "10.240.0.0/16"

        return VPCNetwork(
            name=self._vpc_name,
            region=self._region,
            address_prefix_cidr=prefix,
        )

    def _translate_networks(
        self, networks: list[NetworkSegment], vpc_id: "__builtins__"
    ) -> list[VPCSubnet]:
        """Map source network segments (VLANs, vSwitches) to VPC subnets."""
        subnets: list[VPCSubnet] = []
        for i, net in enumerate(networks):
            zone = f"{self._region}-{(i % 3) + 1}"
            subnets.append(
                VPCSubnet(
                    name=f"subnet-{net.name}".lower().replace(" ", "-"),
                    vpc_id=vpc_id,
                    zone=zone,
                    region=self._region,
                    ipv4_cidr_block=net.cidr,
                    public_gateway=net.metadata.get("network_space") == "PUBLIC",
                    source_network_name=net.name,
                )
            )
        return subnets

    def _translate_security_policies(
        self, policies: list[SecurityPolicy], vpc_id: "UUID"
    ) -> list[VPCSecurityGroup]:
        """Map source firewall/security rules to VPC security groups."""
        if not policies:
            return []

        # Group all rules into a single security group for MVP
        rules: list[VPCSecurityGroupRule] = []
        for policy in policies:
            port_min = policy.port
            port_max = policy.port
            if policy.port_range:
                parts = policy.port_range.split("-")
                if len(parts) == 2:
                    port_min = int(parts[0])
                    port_max = int(parts[1])

            rules.append(
                VPCSecurityGroupRule(
                    direction=policy.direction,
                    protocol=policy.protocol.value,
                    port_min=port_min,
                    port_max=port_max,
                    remote_cidr=policy.source,
                )
            )

        sg = VPCSecurityGroup(
            name=f"{self._vpc_name}-sg",
            vpc_id=vpc_id,
            region=self._region,
            rules=rules,
        )
        return [sg]

    def _translate_compute(
        self,
        compute: list[ComputeResource],
        storage: list,
        vpc_id: "UUID",
        subnets: list[VPCSubnet],
        security_groups: list[VPCSecurityGroup],
    ) -> list[VPCInstance]:
        """Map source VMs to VPC instances."""
        if not subnets:
            return []

        sg_ids = [sg.id for sg in security_groups]

        # Build a lookup: source VM name → list of data volume sizes
        volume_map: dict[str, list[int]] = {}
        for vol in storage:
            # attached_to may be a classic_id or vm_id string
            hostname = vol.metadata.get("hostname", "") or vol.name.rsplit("-", 1)[0]
            volume_map.setdefault(hostname, []).append(vol.size_gb)

        instances: list[VPCInstance] = []
        for i, vm in enumerate(compute):
            subnet = subnets[i % len(subnets)]
            profile = self._select_profile(vm.cpu, vm.memory_gb)
            image = self._select_image(vm.os)
            data_volumes = volume_map.get(vm.name, [])

            instances.append(
                VPCInstance(
                    name=f"vsi-{vm.name}".lower(),
                    vpc_id=vpc_id,
                    subnet_id=subnet.id,
                    zone=subnet.zone,
                    region=self._region,
                    profile=profile,
                    image=image,
                    boot_volume_gb=vm.storage_gb or 100,
                    data_volumes=data_volumes,
                    security_group_ids=sg_ids,
                    source_vm_name=vm.name,
                )
            )
        return instances

    @staticmethod
    def _select_profile(cpu: int, memory_gb: int) -> str:
        """Find the smallest VPC profile that fits the requested CPU and memory."""
        for p_cpu, p_mem, profile_name in PROFILE_MAP:
            if p_cpu >= cpu and p_mem >= memory_gb:
                return profile_name
        return PROFILE_MAP[-1][2]  # largest available

    @staticmethod
    def _select_image(os_string: str) -> str:
        """Map a source OS string to an IBM Cloud VPC image name."""
        os_lower = os_string.lower()
        for key, image in OS_IMAGE_MAP.items():
            if key in os_lower:
                return image
        return "ibm-ubuntu-22-04-4-minimal-amd64-1"  # default fallback
