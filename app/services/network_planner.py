"""Network planner — CIDR allocation with tier-based subnet grouping and security zones.

v1: Sequential CIDR allocation from target range with conflict detection.
v2 (Phase 3): Tier-based allocation using resource tags (tier:web/app/db),
security zone mapping to tiers with configurable override.
"""

import ipaddress
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import ComputeResource, NetworkSegment

logger = structlog.get_logger(__name__)

# Default security zone → tier mapping
DEFAULT_ZONE_TIER_MAP: dict[str, str] = {
    "dmz": "web",
    "trusted": "app",
    "restricted": "db",
    "public": "web",
    "private": "app",
    "data": "db",
}


class SubnetAllocation(BaseModel):
    """A single subnet allocation in the target VPC."""

    source_network_id: str = Field(description="UUID of the source NetworkSegment")
    source_network_name: str = Field(description="Name of the source network")
    source_cidr: str = Field(description="Original CIDR from source platform")
    target_cidr: str = Field(description="Allocated CIDR in target VPC range")
    target_zone: str = Field(description="Target VPC zone")
    host_capacity: int = Field(description="Number of usable host addresses")
    gateway: str = Field(description="Allocated gateway IP")
    tier: str = Field(default="", description="Tier classification (web, app, db)")
    security_zone: str = Field(default="", description="Security zone (dmz, trusted, restricted)")


class NetworkPlanConflict(BaseModel):
    """A detected conflict in the network plan."""

    conflict_type: str = Field(description="overlap, exhaustion, or sizing")
    networks_involved: list[str] = Field(description="Names of conflicting networks")
    message: str = Field(description="Human-readable description")


class TierAllocation(BaseModel):
    """Summary of allocations for a single tier."""

    tier: str = Field(description="Tier name (web, app, db)")
    security_zone: str = Field(default="", description="Mapped security zone")
    subnet_count: int = Field(default=0, description="Number of subnets in this tier")
    total_hosts: int = Field(default=0, description="Total host capacity")
    subnets: list[str] = Field(default_factory=list, description="Allocated subnet CIDRs")


class NetworkPlan(BaseModel):
    """Complete network allocation plan for a migration."""

    vpc_cidr: str = Field(description="VPC address prefix CIDR")
    allocations: list[SubnetAllocation] = Field(default_factory=list)
    conflicts: list[NetworkPlanConflict] = Field(default_factory=list)
    total_hosts_allocated: int = Field(default=0)
    total_hosts_available: int = Field(default=0)
    tier_allocations: list[TierAllocation] = Field(
        default_factory=list, description="Allocation summary by tier"
    )


class NetworkPlanner:
    """Allocates target CIDRs from a configurable VPC address range.

    Instead of preserving source CIDRs (which may conflict or not fit the target),
    this planner allocates fresh subnets from the target VPC range while preserving
    the subnet sizing (prefix length) from the source.

    Supports tier-based allocation: networks are classified into tiers (web, app, db)
    based on resource tags or NSX security zone metadata. Tiers determine subnet
    grouping and can be used for tier-specific security groups.

    Args:
        target_vpc_cidr: The VPC address prefix to allocate subnets from.
            Defaults to "10.240.0.0/16".
        region: Target VPC region. Defaults to "us-south".
        zones: Number of availability zones. Defaults to 3.
        zone_tier_map: Override for security zone → tier mapping.
    """

    def __init__(
        self,
        target_vpc_cidr: str = "10.240.0.0/16",
        region: str = "us-south",
        zones: int = 3,
        zone_tier_map: dict[str, str] | None = None,
    ) -> None:
        self._vpc_cidr = target_vpc_cidr
        self._vpc_network = ipaddress.IPv4Network(target_vpc_cidr, strict=False)
        self._region = region
        self._zones = zones
        self._zone_tier_map = zone_tier_map or DEFAULT_ZONE_TIER_MAP
        self._allocated: list[ipaddress.IPv4Network] = []

    def plan(
        self,
        networks: list[NetworkSegment],
        compute: list[ComputeResource] | None = None,
    ) -> NetworkPlan:
        """Generate a network allocation plan for the given source networks.

        Allocates fresh CIDRs from the target VPC range, preserving
        the prefix length (subnet sizing) from each source network.
        Distributes subnets across availability zones round-robin.
        Classifies networks into tiers based on tags and security zone metadata.

        Args:
            networks: Source NetworkSegments to plan for.
            compute: Optional compute resources for tier inference from VM tags.

        Returns:
            NetworkPlan with allocations, conflicts, tier summaries, and capacity info.
        """
        logger.info(
            "network_planning_started",
            source_networks=len(networks),
            target_vpc_cidr=self._vpc_cidr,
        )

        self._allocated = []
        allocations: list[SubnetAllocation] = []
        conflicts: list[NetworkPlanConflict] = []

        # Build tier lookup from compute resources connected to each network
        network_tier_from_compute = self._infer_tiers_from_compute(networks, compute or [])

        # Parse source networks and determine required prefix lengths + tiers
        allocation_requests: list[tuple[NetworkSegment, int, str, str]] = []
        for net in networks:
            try:
                source_net = ipaddress.IPv4Network(net.cidr, strict=False)
                prefix_len = source_net.prefixlen
            except (ValueError, ipaddress.AddressValueError):
                conflicts.append(NetworkPlanConflict(
                    conflict_type="sizing",
                    networks_involved=[net.name],
                    message=f"Cannot parse source CIDR '{net.cidr}' — using /24 default",
                ))
                prefix_len = 24

            # Ensure prefix fits within VPC
            if prefix_len < self._vpc_network.prefixlen:
                conflicts.append(NetworkPlanConflict(
                    conflict_type="sizing",
                    networks_involved=[net.name],
                    message=(
                        f"Source subnet /{prefix_len} is larger than VPC /{self._vpc_network.prefixlen} — "
                        f"will use /{self._vpc_network.prefixlen + 2} instead"
                    ),
                ))
                prefix_len = self._vpc_network.prefixlen + 2

            # Determine tier and security zone
            tier, security_zone = self._classify_network_tier(net, network_tier_from_compute)

            allocation_requests.append((net, prefix_len, tier, security_zone))

        # Sort by tier (group same tiers together), then by prefix length
        tier_order = {"web": 0, "app": 1, "db": 2}
        allocation_requests.sort(
            key=lambda x: (tier_order.get(x[2], 99), x[1])
        )

        # Allocate subnets — round-robin zones within each tier group
        tier_zone_counters: dict[str, int] = {}
        for net, prefix_len, tier, security_zone in allocation_requests:
            tier_key = tier or "default"
            counter = tier_zone_counters.get(tier_key, 0)
            zone = f"{self._region}-{(counter % self._zones) + 1}"
            tier_zone_counters[tier_key] = counter + 1

            allocated_cidr = self._allocate_subnet(prefix_len)

            if allocated_cidr is None:
                conflicts.append(NetworkPlanConflict(
                    conflict_type="exhaustion",
                    networks_involved=[net.name],
                    message=(
                        f"Cannot allocate /{prefix_len} subnet for '{net.name}' — "
                        f"VPC address space {self._vpc_cidr} exhausted"
                    ),
                ))
                continue

            # Gateway is first usable address
            gateway = str(list(allocated_cidr.hosts())[0]) if allocated_cidr.num_addresses > 2 else ""
            host_count = max(0, allocated_cidr.num_addresses - 2)  # subtract network + broadcast

            allocations.append(SubnetAllocation(
                source_network_id=str(net.id),
                source_network_name=net.name,
                source_cidr=net.cidr,
                target_cidr=str(allocated_cidr),
                target_zone=zone,
                host_capacity=host_count,
                gateway=gateway,
                tier=tier,
                security_zone=security_zone,
            ))

        # Detect source-side CIDR overlaps (informational)
        self._detect_source_overlaps(networks, conflicts)

        total_hosts = sum(a.host_capacity for a in allocations)
        total_available = self._vpc_network.num_addresses - 2

        # Build tier summaries
        tier_allocs = self._build_tier_allocations(allocations)

        result = NetworkPlan(
            vpc_cidr=self._vpc_cidr,
            allocations=allocations,
            conflicts=conflicts,
            total_hosts_allocated=total_hosts,
            total_hosts_available=total_available,
            tier_allocations=tier_allocs,
        )

        logger.info(
            "network_planning_completed",
            subnets_allocated=len(allocations),
            conflicts=len(conflicts),
            hosts_allocated=total_hosts,
            tiers=[t.tier for t in tier_allocs],
        )
        return result

    def _allocate_subnet(self, prefix_len: int) -> ipaddress.IPv4Network | None:
        """Find the next available subnet with the given prefix length.

        Uses a simple sequential allocation strategy — walks through the VPC
        address space and finds the first non-overlapping block.
        """
        try:
            candidate_subnets = self._vpc_network.subnets(new_prefix=prefix_len)
        except ValueError:
            return None

        for candidate in candidate_subnets:
            if not any(candidate.overlaps(existing) for existing in self._allocated):
                self._allocated.append(candidate)
                return candidate

        return None  # Address space exhausted

    def _classify_network_tier(
        self,
        net: NetworkSegment,
        compute_tier_map: dict[str, str],
    ) -> tuple[str, str]:
        """Determine tier and security zone for a network segment.

        Priority order:
        1. Network's own tier tag (e.g., tier:web on NSX segment)
        2. Security zone metadata mapped to tier via zone_tier_map
        3. Tier inferred from connected compute resource tags
        4. Tier from network zone field
        5. Empty string (unclassified)

        Returns:
            (tier, security_zone) tuple.
        """
        # 1. Direct tier tag on the network
        tier = net.tags.get("tier", "")
        security_zone = net.metadata.get("security_zone", "") or net.tags.get("zone", "")

        if tier:
            return tier, security_zone

        # 2. Map security zone to tier
        if security_zone:
            mapped_tier = self._zone_tier_map.get(security_zone.lower(), "")
            if mapped_tier:
                return mapped_tier, security_zone

        # 3. From connected compute resources
        net_id_str = str(net.id)
        if net_id_str in compute_tier_map:
            return compute_tier_map[net_id_str], security_zone

        # 4. From the zone field
        if net.zone:
            zone_lower = net.zone.lower()
            # Check if zone matches a known tier directly
            if zone_lower in ("web", "app", "db"):
                return zone_lower, security_zone
            # Check if zone maps via zone_tier_map
            mapped = self._zone_tier_map.get(zone_lower, "")
            if mapped:
                return mapped, security_zone

        return "", security_zone

    def _infer_tiers_from_compute(
        self,
        networks: list[NetworkSegment],
        compute: list[ComputeResource],
    ) -> dict[str, str]:
        """Build network_id → tier mapping from connected compute resource tags.

        If a network has connected VMs that share a tier tag, that tier
        is attributed to the network.
        """
        result: dict[str, str] = {}
        for net in networks:
            tiers_seen: dict[str, int] = {}
            for vm in compute:
                if net.id in vm.network_interfaces:
                    vm_tier = vm.tags.get("tier", "")
                    if vm_tier:
                        tiers_seen[vm_tier] = tiers_seen.get(vm_tier, 0) + 1

            if tiers_seen:
                # Use the most common tier among connected VMs
                dominant_tier = max(tiers_seen, key=tiers_seen.get)  # type: ignore[arg-type]
                result[str(net.id)] = dominant_tier

        return result

    @staticmethod
    def _build_tier_allocations(
        allocations: list[SubnetAllocation],
    ) -> list[TierAllocation]:
        """Build tier allocation summaries from subnet allocations."""
        by_tier: dict[str, TierAllocation] = {}
        for alloc in allocations:
            tier = alloc.tier or "default"
            if tier not in by_tier:
                by_tier[tier] = TierAllocation(
                    tier=tier,
                    security_zone=alloc.security_zone,
                )
            ta = by_tier[tier]
            ta.subnet_count += 1
            ta.total_hosts += alloc.host_capacity
            ta.subnets.append(alloc.target_cidr)

        return list(by_tier.values())

    def _detect_source_overlaps(
        self,
        networks: list[NetworkSegment],
        conflicts: list[NetworkPlanConflict],
    ) -> None:
        """Detect overlapping CIDRs in the source networks (informational)."""
        parsed: list[tuple[str, ipaddress.IPv4Network]] = []
        for net in networks:
            try:
                parsed.append((net.name, ipaddress.IPv4Network(net.cidr, strict=False)))
            except (ValueError, ipaddress.AddressValueError):
                continue

        for i, (name_a, net_a) in enumerate(parsed):
            for name_b, net_b in parsed[i + 1:]:
                if net_a.overlaps(net_b) and str(net_a) != str(net_b):
                    conflicts.append(NetworkPlanConflict(
                        conflict_type="overlap",
                        networks_involved=[name_a, name_b],
                        message=(
                            f"Source networks '{name_a}' ({net_a}) and "
                            f"'{name_b}' ({net_b}) overlap — "
                            f"target allocations are non-overlapping"
                        ),
                    ))
