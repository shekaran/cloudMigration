"""Translation service — converts canonical model to IBM VPC target model."""

from __future__ import annotations

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
from app.services.network_planner import NetworkPlan
from app.services.strategy import MigrationStrategy, StrategyResult

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

# Replatform profiles — optimized instance types for stateful/complex workloads
REPLATFORM_PROFILE_MAP: list[tuple[int, int, str]] = [
    (2, 16, "mx2-2x16"),
    (4, 32, "mx2-4x32"),
    (8, 64, "mx2-8x64"),
    (16, 128, "mx2-16x128"),
    (32, 256, "mx2-32x256"),
]


class TranslationService:
    """Translates canonical DiscoveredResources into IBM VPC target resources.

    Supports strategy-aware translation — different strategies produce
    different VPC configurations (e.g., replatform uses memory-optimized profiles).
    Supports network plan — uses allocated CIDRs instead of source CIDRs.
    """

    def __init__(self, vpc_name: str = "migration-vpc", region: str = "us-south") -> None:
        self._vpc_name = vpc_name
        self._region = region

    def translate(
        self,
        canonical: DiscoveredResources,
        strategy_result: StrategyResult | None = None,
        network_plan: NetworkPlan | None = None,
    ) -> VPCTranslationResult:
        """Convert canonical resources to a complete VPC translation result.

        Args:
            canonical: Normalized resources from discovery.
            strategy_result: Optional strategy assignments. If None, all resources
                use lift-and-shift.
            network_plan: Optional network allocation plan. If None, source CIDRs
                are preserved (Phase 1 behavior).

        Returns:
            VPCTranslationResult with VPC, subnets, security groups, and instances.
        """
        logger.info("translation_started", resource_count=canonical.resource_count)

        vpc = self._create_vpc(canonical, network_plan)
        subnets = self._translate_networks(canonical.networks, vpc.id, network_plan)
        security_groups = self._translate_security_policies(
            canonical.security_policies, vpc.id
        )
        instances = self._translate_compute(
            canonical.compute,
            canonical.storage,
            vpc.id,
            subnets,
            security_groups,
            strategy_result,
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

    def _create_vpc(
        self,
        canonical: DiscoveredResources,
        network_plan: NetworkPlan | None,
    ) -> VPCNetwork:
        """Create the target VPC resource."""
        if network_plan:
            prefix = network_plan.vpc_cidr
        elif canonical.networks:
            prefix = canonical.networks[0].cidr
        else:
            prefix = "10.240.0.0/16"

        return VPCNetwork(
            name=self._vpc_name,
            region=self._region,
            address_prefix_cidr=prefix,
        )

    def _translate_networks(
        self,
        networks: list[NetworkSegment],
        vpc_id,
        network_plan: NetworkPlan | None,
    ) -> list[VPCSubnet]:
        """Map source network segments to VPC subnets.

        If a network plan is provided, uses allocated target CIDRs and zones.
        Otherwise falls back to Phase 1 behavior (source CIDRs preserved).
        """
        if network_plan and network_plan.allocations:
            # Use network plan allocations
            alloc_by_source = {
                a.source_network_id: a for a in network_plan.allocations
            }
            subnets: list[VPCSubnet] = []
            for net in networks:
                alloc = alloc_by_source.get(str(net.id))
                if alloc:
                    subnets.append(
                        VPCSubnet(
                            name=f"subnet-{net.name}".lower().replace(" ", "-"),
                            vpc_id=vpc_id,
                            zone=alloc.target_zone,
                            region=self._region,
                            ipv4_cidr_block=alloc.target_cidr,
                            public_gateway=net.metadata.get("network_space") == "PUBLIC",
                            source_network_name=net.name,
                        )
                    )
                else:
                    # Fallback for unallocated networks
                    subnets.append(
                        VPCSubnet(
                            name=f"subnet-{net.name}".lower().replace(" ", "-"),
                            vpc_id=vpc_id,
                            zone=f"{self._region}-1",
                            region=self._region,
                            ipv4_cidr_block=net.cidr,
                            public_gateway=net.metadata.get("network_space") == "PUBLIC",
                            source_network_name=net.name,
                        )
                    )
            return subnets

        # Phase 1 fallback: preserve source CIDRs
        subnets = []
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
        self, policies: list[SecurityPolicy], vpc_id
    ) -> list[VPCSecurityGroup]:
        """Map source firewall/security policies to VPC security groups."""
        if not policies:
            return []

        security_groups: list[VPCSecurityGroup] = []
        for policy in policies:
            vpc_rules: list[VPCSecurityGroupRule] = []
            for rule in policy.rules:
                port_min = rule.port
                port_max = rule.port
                if rule.port_range:
                    parts = rule.port_range.split("-")
                    if len(parts) == 2:
                        port_min = int(parts[0])
                        port_max = int(parts[1])

                vpc_rules.append(
                    VPCSecurityGroupRule(
                        direction=rule.direction,
                        protocol=rule.protocol.value,
                        port_min=port_min,
                        port_max=port_max,
                        remote_cidr=rule.source,
                    )
                )

            security_groups.append(
                VPCSecurityGroup(
                    name=f"{self._vpc_name}-{policy.name}".lower().replace(" ", "-"),
                    vpc_id=vpc_id,
                    region=self._region,
                    rules=vpc_rules,
                )
            )
        return security_groups

    def _translate_compute(
        self,
        compute: list[ComputeResource],
        storage: list,
        vpc_id,
        subnets: list[VPCSubnet],
        security_groups: list[VPCSecurityGroup],
        strategy_result: StrategyResult | None = None,
    ) -> list[VPCInstance]:
        """Map source VMs to VPC instances.

        Strategy-aware: replatform VMs get memory-optimized profiles and larger
        boot volumes. Rebuild VMs get fresh minimal instances.
        """
        if not subnets:
            return []

        sg_ids = [sg.id for sg in security_groups]

        # Build volume lookup
        volume_map: dict[str, list[int]] = {}
        for vol in storage:
            hostname = vol.metadata.get("hostname", "") or vol.metadata.get("vm_name", "") or vol.name.rsplit("-", 1)[0]
            volume_map.setdefault(hostname, []).append(vol.size_gb)

        instances: list[VPCInstance] = []
        for i, vm in enumerate(compute):
            subnet = subnets[i % len(subnets)]
            data_volumes = volume_map.get(vm.name, [])

            # Determine strategy for this VM
            vm_strategy = MigrationStrategy.LIFT_AND_SHIFT
            if strategy_result:
                vm_strategy = strategy_result.assignments.get(
                    str(vm.id), MigrationStrategy.LIFT_AND_SHIFT
                )

            # Strategy-specific translation
            if vm_strategy == MigrationStrategy.REPLATFORM:
                # Replatform: memory-optimized profiles, larger boot volume
                profile = self._select_profile_replatform(vm.cpu, vm.memory_gb)
                boot_gb = max(vm.storage_gb or 100, 200)  # minimum 200GB for replatform
            elif vm_strategy == MigrationStrategy.REBUILD:
                # Rebuild: minimal fresh instance, no data volumes carried over
                profile = self._select_profile(vm.cpu, vm.memory_gb)
                boot_gb = 100
                data_volumes = []  # rebuild doesn't carry data volumes
            else:
                # Lift-and-shift: direct mapping
                profile = self._select_profile(vm.cpu, vm.memory_gb)
                boot_gb = vm.storage_gb or 100

            image = self._select_image(vm.os)

            instances.append(
                VPCInstance(
                    name=f"vsi-{vm.name}".lower(),
                    vpc_id=vpc_id,
                    subnet_id=subnet.id,
                    zone=subnet.zone,
                    region=self._region,
                    profile=profile,
                    image=image,
                    boot_volume_gb=boot_gb,
                    data_volumes=data_volumes,
                    security_group_ids=sg_ids,
                    source_vm_name=vm.name,
                    migration_strategy=vm_strategy.value,
                )
            )
        return instances

    @staticmethod
    def _select_profile(cpu: int, memory_gb: int) -> str:
        """Find the smallest standard VPC profile that fits."""
        for p_cpu, p_mem, profile_name in PROFILE_MAP:
            if p_cpu >= cpu and p_mem >= memory_gb:
                return profile_name
        return PROFILE_MAP[-1][2]

    @staticmethod
    def _select_profile_replatform(cpu: int, memory_gb: int) -> str:
        """Find the smallest memory-optimized VPC profile that fits (for replatform)."""
        for p_cpu, p_mem, profile_name in REPLATFORM_PROFILE_MAP:
            if p_cpu >= cpu and p_mem >= memory_gb:
                return profile_name
        return REPLATFORM_PROFILE_MAP[-1][2]

    @staticmethod
    def _select_image(os_string: str) -> str:
        """Map a source OS string to an IBM Cloud VPC image name."""
        os_lower = os_string.lower()
        for key, image in OS_IMAGE_MAP.items():
            if key in os_lower:
                return image
        return "ibm-ubuntu-22-04-4-minimal-amd64-1"
