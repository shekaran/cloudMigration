"""Validation engine — pre-migration checks with severity levels."""

import ipaddress
from enum import Enum
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from app.graph.engine import DependencyGraph
from app.models.canonical import (
    ComputeResource,
    NetworkSegment,
    SecurityPolicy,
    StorageVolume,
)
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    """Validation finding severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationFinding(BaseModel):
    """A single validation check result."""

    check_name: str = Field(description="Name of the validation check")
    severity: Severity = Field(description="Finding severity")
    resource_id: str | None = Field(default=None, description="UUID of the affected resource")
    resource_name: str | None = Field(default=None, description="Name of the affected resource")
    message: str = Field(description="Human-readable description of the finding")


class ValidationResult(BaseModel):
    """Complete validation result for a set of discovered resources."""

    passed: bool = Field(description="True if no ERROR-level findings")
    findings: list[ValidationFinding] = Field(default_factory=list)
    error_count: int = Field(default=0)
    warning_count: int = Field(default=0)
    info_count: int = Field(default=0)
    checks_run: int = Field(default=0, description="Total number of checks executed")


# Supported OS families for VPC migration
_SUPPORTED_OS_FAMILIES = {"ubuntu", "centos", "rhel", "redhat", "debian", "windows", "sles"}

# VPC instance limits
_MAX_VCPU = 64
_MAX_MEMORY_GB = 256
_MAX_VOLUME_GB = 16000
_MAX_SECURITY_RULES = 50
_MAX_NICS_PER_INSTANCE = 5


class ValidationEngine:
    """Runs pre-migration validation checks.

    Default behavior blocks execution on ERROR findings.
    Can be overridden with skip_validation=True on execution,
    in which case all errors are collected and reported post-execution.
    """

    def validate(
        self,
        resources: DiscoveredResources,
        graph: DependencyGraph,
    ) -> ValidationResult:
        """Run all validation checks against discovered resources.

        Args:
            resources: Canonical resources to validate.
            graph: Dependency graph for relationship checks.

        Returns:
            ValidationResult with all findings.
        """
        logger.info("validation_started", resource_count=resources.resource_count)

        findings: list[ValidationFinding] = []
        checks_run = 0

        # Compute checks
        for vm in resources.compute:
            findings.extend(self._check_compute(vm))
            checks_run += 5  # 5 checks per compute

        # Network checks
        findings.extend(self._check_networks(resources.networks))
        checks_run += 3

        # Security policy checks
        for sp in resources.security_policies:
            findings.extend(self._check_security_policy(sp))
            checks_run += 2

        # Storage checks
        for vol in resources.storage:
            findings.extend(self._check_storage(vol, resources.compute))
            checks_run += 3

        # Graph checks
        findings.extend(self._check_graph(graph))
        checks_run += 2

        # Cross-resource reference checks
        findings.extend(self._check_references(resources))
        checks_run += 1

        errors = sum(1 for f in findings if f.severity == Severity.ERROR)
        warnings = sum(1 for f in findings if f.severity == Severity.WARNING)
        infos = sum(1 for f in findings if f.severity == Severity.INFO)

        result = ValidationResult(
            passed=errors == 0,
            findings=findings,
            error_count=errors,
            warning_count=warnings,
            info_count=infos,
            checks_run=checks_run,
        )

        logger.info(
            "validation_completed",
            passed=result.passed,
            errors=errors,
            warnings=warnings,
            infos=infos,
            checks_run=checks_run,
        )
        return result

    def _check_compute(self, vm: ComputeResource) -> list[ValidationFinding]:
        """Validate a compute resource."""
        findings: list[ValidationFinding] = []

        # OS compatibility
        os_lower = vm.os.lower()
        if not any(family in os_lower for family in _SUPPORTED_OS_FAMILIES):
            findings.append(ValidationFinding(
                check_name="os_compatibility",
                severity=Severity.ERROR,
                resource_id=str(vm.id),
                resource_name=vm.name,
                message=f"Unsupported OS '{vm.os}' — cannot map to VPC image",
            ))

        # CPU limits
        if vm.cpu > _MAX_VCPU:
            findings.append(ValidationFinding(
                check_name="cpu_limit",
                severity=Severity.ERROR,
                resource_id=str(vm.id),
                resource_name=vm.name,
                message=f"CPU count {vm.cpu} exceeds VPC maximum of {_MAX_VCPU}",
            ))

        # Memory limits
        if vm.memory_gb > _MAX_MEMORY_GB:
            findings.append(ValidationFinding(
                check_name="memory_limit",
                severity=Severity.ERROR,
                resource_id=str(vm.id),
                resource_name=vm.name,
                message=f"Memory {vm.memory_gb}GB exceeds VPC maximum of {_MAX_MEMORY_GB}GB",
            ))

        # Network interface count
        if len(vm.network_interfaces) > _MAX_NICS_PER_INSTANCE:
            findings.append(ValidationFinding(
                check_name="nic_limit",
                severity=Severity.WARNING,
                resource_id=str(vm.id),
                resource_name=vm.name,
                message=(
                    f"VM has {len(vm.network_interfaces)} NICs — "
                    f"VPC supports max {_MAX_NICS_PER_INSTANCE}"
                ),
            ))

        # Missing IP addresses (info)
        if not vm.ip_addresses:
            findings.append(ValidationFinding(
                check_name="no_ip_address",
                severity=Severity.INFO,
                resource_id=str(vm.id),
                resource_name=vm.name,
                message="VM has no IP addresses — VPC will auto-assign",
            ))

        return findings

    def _check_networks(self, networks: list[NetworkSegment]) -> list[ValidationFinding]:
        """Validate network segments and detect CIDR conflicts."""
        findings: list[ValidationFinding] = []

        seen_cidrs: dict[str, str] = {}  # cidr → network name
        parsed_nets: list[tuple[str, str, ipaddress.IPv4Network]] = []

        for net in networks:
            # CIDR format validation
            try:
                parsed = ipaddress.IPv4Network(net.cidr, strict=False)
                parsed_nets.append((str(net.id), net.name, parsed))
            except (ValueError, ipaddress.AddressValueError):
                findings.append(ValidationFinding(
                    check_name="invalid_cidr",
                    severity=Severity.ERROR,
                    resource_id=str(net.id),
                    resource_name=net.name,
                    message=f"Invalid CIDR block: '{net.cidr}'",
                ))
                continue

            # Duplicate CIDR detection
            if net.cidr in seen_cidrs:
                findings.append(ValidationFinding(
                    check_name="duplicate_cidr",
                    severity=Severity.WARNING,
                    resource_id=str(net.id),
                    resource_name=net.name,
                    message=f"CIDR {net.cidr} duplicates network '{seen_cidrs[net.cidr]}'",
                ))
            seen_cidrs[net.cidr] = net.name

        # Overlap detection
        for i, (id_a, name_a, net_a) in enumerate(parsed_nets):
            for id_b, name_b, net_b in parsed_nets[i + 1:]:
                if net_a.overlaps(net_b) and str(net_a) != str(net_b):
                    findings.append(ValidationFinding(
                        check_name="cidr_overlap",
                        severity=Severity.WARNING,
                        resource_id=id_a,
                        resource_name=name_a,
                        message=f"CIDR {net_a} overlaps with {net_b} (network '{name_b}')",
                    ))

        return findings

    def _check_security_policy(self, sp: SecurityPolicy) -> list[ValidationFinding]:
        """Validate a security policy."""
        findings: list[ValidationFinding] = []

        # Rule count limit
        if len(sp.rules) > _MAX_SECURITY_RULES:
            findings.append(ValidationFinding(
                check_name="security_rule_limit",
                severity=Severity.WARNING,
                resource_id=str(sp.id),
                resource_name=sp.name,
                message=(
                    f"Policy has {len(sp.rules)} rules — "
                    f"VPC security groups support max {_MAX_SECURITY_RULES}"
                ),
            ))

        # Validate rule fields
        for i, rule in enumerate(sp.rules):
            if rule.protocol.value not in ("tcp", "udp", "icmp", "all"):
                findings.append(ValidationFinding(
                    check_name="unsupported_protocol",
                    severity=Severity.ERROR,
                    resource_id=str(sp.id),
                    resource_name=sp.name,
                    message=f"Rule {i}: unsupported protocol '{rule.protocol.value}'",
                ))

        return findings

    def _check_storage(
        self,
        vol: StorageVolume,
        compute: list[ComputeResource],
    ) -> list[ValidationFinding]:
        """Validate a storage volume."""
        findings: list[ValidationFinding] = []

        # Size limit
        if vol.size_gb > _MAX_VOLUME_GB:
            findings.append(ValidationFinding(
                check_name="volume_size_limit",
                severity=Severity.ERROR,
                resource_id=str(vol.id),
                resource_name=vol.name,
                message=f"Volume size {vol.size_gb}GB exceeds VPC maximum of {_MAX_VOLUME_GB}GB",
            ))

        # Orphaned volume (not attached)
        if vol.attached_to is None:
            findings.append(ValidationFinding(
                check_name="orphaned_volume",
                severity=Severity.WARNING,
                resource_id=str(vol.id),
                resource_name=vol.name,
                message="Volume not attached to any compute resource",
            ))
        else:
            # Verify attachment target exists
            compute_ids = {vm.id for vm in compute}
            if vol.attached_to not in compute_ids:
                findings.append(ValidationFinding(
                    check_name="invalid_attachment",
                    severity=Severity.ERROR,
                    resource_id=str(vol.id),
                    resource_name=vol.name,
                    message=f"Volume attached to non-existent compute resource {vol.attached_to}",
                ))

        return findings

    def _check_graph(self, graph: DependencyGraph) -> list[ValidationFinding]:
        """Validate the dependency graph."""
        findings: list[ValidationFinding] = []

        # Cycle detection
        cycles = graph.detect_cycles()
        if cycles:
            for cycle in cycles:
                cycle_str = " → ".join(str(uid)[:8] for uid in cycle)
                findings.append(ValidationFinding(
                    check_name="cyclic_dependency",
                    severity=Severity.ERROR,
                    message=f"Circular dependency detected: {cycle_str}",
                ))

        # Isolated nodes (no dependencies at all — info only)
        for node_id in graph.nodes:
            deps = graph.dependencies_of(node_id)
            dependents = graph.dependents_of(node_id)
            if not deps and not dependents:
                findings.append(ValidationFinding(
                    check_name="isolated_resource",
                    severity=Severity.INFO,
                    resource_id=str(node_id),
                    message="Resource has no dependencies — will be migrated independently",
                ))

        return findings

    def _check_references(self, resources: DiscoveredResources) -> list[ValidationFinding]:
        """Validate that all UUID cross-references resolve to existing resources."""
        findings: list[ValidationFinding] = []

        all_ids: set[UUID] = set()
        for vm in resources.compute:
            all_ids.add(vm.id)
        for net in resources.networks:
            all_ids.add(net.id)
        for sp in resources.security_policies:
            all_ids.add(sp.id)
        for vol in resources.storage:
            all_ids.add(vol.id)

        # Check compute cross-references
        for vm in resources.compute:
            for disk_id in vm.disks:
                if disk_id not in all_ids:
                    findings.append(ValidationFinding(
                        check_name="dangling_disk_ref",
                        severity=Severity.ERROR,
                        resource_id=str(vm.id),
                        resource_name=vm.name,
                        message=f"Disk reference {disk_id} does not exist",
                    ))
            for net_id in vm.network_interfaces:
                if net_id not in all_ids:
                    findings.append(ValidationFinding(
                        check_name="dangling_network_ref",
                        severity=Severity.ERROR,
                        resource_id=str(vm.id),
                        resource_name=vm.name,
                        message=f"Network interface reference {net_id} does not exist",
                    ))

        return findings
