"""Network planner v1 — CIDR allocation from target range with conflict detection."""

import ipaddress
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import NetworkSegment

logger = structlog.get_logger(__name__)


class SubnetAllocation(BaseModel):
    """A single subnet allocation in the target VPC."""

    source_network_id: str = Field(description="UUID of the source NetworkSegment")
    source_network_name: str = Field(description="Name of the source network")
    source_cidr: str = Field(description="Original CIDR from source platform")
    target_cidr: str = Field(description="Allocated CIDR in target VPC range")
    target_zone: str = Field(description="Target VPC zone")
    host_capacity: int = Field(description="Number of usable host addresses")
    gateway: str = Field(description="Allocated gateway IP")


class NetworkPlanConflict(BaseModel):
    """A detected conflict in the network plan."""

    conflict_type: str = Field(description="overlap, exhaustion, or sizing")
    networks_involved: list[str] = Field(description="Names of conflicting networks")
    message: str = Field(description="Human-readable description")


class NetworkPlan(BaseModel):
    """Complete network allocation plan for a migration."""

    vpc_cidr: str = Field(description="VPC address prefix CIDR")
    allocations: list[SubnetAllocation] = Field(default_factory=list)
    conflicts: list[NetworkPlanConflict] = Field(default_factory=list)
    total_hosts_allocated: int = Field(default=0)
    total_hosts_available: int = Field(default=0)


class NetworkPlanner:
    """Allocates target CIDRs from a configurable VPC address range.

    Instead of preserving source CIDRs (which may conflict or not fit the target),
    this planner allocates fresh subnets from the target VPC range while preserving
    the subnet sizing (prefix length) from the source.

    Args:
        target_vpc_cidr: The VPC address prefix to allocate subnets from.
            Defaults to "10.240.0.0/16".
        region: Target VPC region. Defaults to "us-south".
        zones: Number of availability zones. Defaults to 3.
    """

    def __init__(
        self,
        target_vpc_cidr: str = "10.240.0.0/16",
        region: str = "us-south",
        zones: int = 3,
    ) -> None:
        self._vpc_cidr = target_vpc_cidr
        self._vpc_network = ipaddress.IPv4Network(target_vpc_cidr, strict=False)
        self._region = region
        self._zones = zones
        self._allocated: list[ipaddress.IPv4Network] = []

    def plan(self, networks: list[NetworkSegment]) -> NetworkPlan:
        """Generate a network allocation plan for the given source networks.

        Allocates fresh CIDRs from the target VPC range, preserving
        the prefix length (subnet sizing) from each source network.
        Distributes subnets across availability zones round-robin.

        Args:
            networks: Source NetworkSegments to plan for.

        Returns:
            NetworkPlan with allocations, conflicts, and capacity info.
        """
        logger.info(
            "network_planning_started",
            source_networks=len(networks),
            target_vpc_cidr=self._vpc_cidr,
        )

        self._allocated = []
        allocations: list[SubnetAllocation] = []
        conflicts: list[NetworkPlanConflict] = []

        # Parse source networks and determine required prefix lengths
        allocation_requests: list[tuple[NetworkSegment, int]] = []
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

            allocation_requests.append((net, prefix_len))

        # Sort by prefix length (smaller prefix = larger subnet first) for better packing
        allocation_requests.sort(key=lambda x: x[1])

        # Allocate subnets
        for i, (net, prefix_len) in enumerate(allocation_requests):
            zone = f"{self._region}-{(i % self._zones) + 1}"
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
            ))

        # Detect source-side CIDR overlaps (informational)
        self._detect_source_overlaps(networks, conflicts)

        total_hosts = sum(a.host_capacity for a in allocations)
        total_available = self._vpc_network.num_addresses - 2

        result = NetworkPlan(
            vpc_cidr=self._vpc_cidr,
            allocations=allocations,
            conflicts=conflicts,
            total_hosts_allocated=total_hosts,
            total_hosts_available=total_available,
        )

        logger.info(
            "network_planning_completed",
            subnets_allocated=len(allocations),
            conflicts=len(conflicts),
            hosts_allocated=total_hosts,
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
