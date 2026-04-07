"""Hyper-V adapter — discovers VMs with VHD/VHDX, checkpoints, replication, SCVMM."""

from typing import Any
from uuid import UUID

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.adapters.hyperv.mock_data import HYPERV_MOCK_DATA
from app.models.canonical import (
    ComputeResource,
    ComputeType,
    NetworkSegment,
    NetworkType,
    ProtocolType,
    SecurityPolicy,
    SecurityPolicyType,
    SecurityRule,
    StorageVolume,
    StorageType,
)
from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class HyperVAdapter(AbstractBaseAdapter):
    """Adapter for Microsoft Hyper-V / SCVMM discovery and normalization."""

    @property
    def platform_name(self) -> str:
        return "hyperv"

    async def discover(self) -> dict[str, Any]:
        """Return mocked Hyper-V / SCVMM API data."""
        logger.info("discovery_started", platform=self.platform_name)
        raw_data = HYPERV_MOCK_DATA
        vms = raw_data.get("virtual_machines", [])
        replicated = sum(1 for v in vms if v.get("replication", {}).get("enabled"))
        checkpoints = sum(len(v.get("checkpoints", [])) for v in vms)
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            vm_count=len(vms),
            vswitch_count=len(raw_data.get("virtual_switches", [])),
            replicated_vms=replicated,
            total_checkpoints=checkpoints,
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw Hyper-V data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        networks = self._normalize_vswitches(raw_data.get("virtual_switches", []))
        storage = self._normalize_storage(raw_data.get("virtual_machines", []))
        compute = self._normalize_vms(
            raw_data.get("virtual_machines", []), networks, storage
        )
        security_policies = self._normalize_firewalls(
            raw_data.get("firewalls", []), compute
        )

        # Link security groups to compute
        for vm in compute:
            for policy in security_policies:
                if vm.id in policy.applied_to and policy.id not in vm.security_groups:
                    vm.security_groups.append(policy.id)

        # Link connected_resources on networks
        network_by_name = {n.name: n for n in networks}
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            for nic in raw_vm.get("network_adapters", []):
                switch_name = nic.get("switch_name", "")
                net = network_by_name.get(switch_name)
                if net and vm.id not in net.connected_resources:
                    net.connected_resources.append(vm.id)

        result = DiscoveredResources(
            compute=compute,
            networks=networks,
            security_policies=security_policies,
            storage=storage,
        )
        logger.info(
            "normalization_completed",
            platform=self.platform_name,
            total_resources=result.resource_count,
            vms=len(compute),
            vhd_volumes=len(storage),
        )
        return result

    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Stub — full translation implemented via TranslationService."""
        return {"status": "not_implemented"}

    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Stub — full migration implemented via Orchestrator."""
        return {"status": "not_implemented"}

    # --- Private helpers ---

    def _normalize_vms(
        self,
        vms: list[dict],
        networks: list[NetworkSegment],
        storage: list[StorageVolume],
    ) -> list[ComputeResource]:
        """Map Hyper-V VMs to ComputeResource."""
        network_by_name = {n.name: n.id for n in networks}

        # Build storage UUID lookup: vm_name → list of StorageVolume UUIDs
        storage_by_vm: dict[str, list[UUID]] = {}
        for vol in storage:
            vm_name = vol.metadata.get("vm_name", "")
            storage_by_vm.setdefault(vm_name, []).append(vol.id)

        results: list[ComputeResource] = []
        for vm in vms:
            os_info = vm.get("os", {})
            cpu_info = vm.get("cpu", {})
            memory_info = vm.get("memory", {})
            cluster_info = vm.get("cluster", {})
            replication = vm.get("replication", {})
            scvmm = vm.get("scvmm", {})
            tags = vm.get("tags", {})
            vm_name = vm.get("name", "unknown")

            # Memory: use startup_mb (or maximum_mb for static)
            memory_mb = memory_info.get("startup_mb", 1024)
            memory_gb = memory_mb // 1024

            # Collect IPs and network interface UUIDs
            ip_addresses: list[str] = []
            net_iface_ids: list[UUID] = []
            for nic in vm.get("network_adapters", []):
                ip = nic.get("ip_address", "")
                if ip:
                    ip_addresses.append(ip)
                switch_name = nic.get("switch_name", "")
                net_id = network_by_name.get(switch_name)
                if net_id and net_id not in net_iface_ids:
                    net_iface_ids.append(net_id)

            # Boot disk = first disk max_size_gb
            disks = vm.get("disks", [])
            boot_disk_gb = disks[0].get("max_size_gb", 0) if disks else 0

            disk_ids = storage_by_vm.get(vm_name, [])

            # Statefulness from tier
            stateful = tags.get("tier") in ("db", "data")

            os_ref = os_info.get("reference_code", os_info.get("name", "unknown"))

            cr = ComputeResource(
                name=vm_name,
                platform=self.platform_name,
                region=cluster_info.get("node", "").split(".")[0] if cluster_info.get("node") else "",
                type=ComputeType.VM,
                cpu=cpu_info.get("count", 1),
                memory_gb=max(memory_gb, 1),
                os=os_ref.lower(),
                image=f"{os_info.get('name', '')} {os_info.get('version', '')}",
                storage_gb=boot_disk_gb,
                ip_addresses=ip_addresses,
                disks=disk_ids,
                network_interfaces=net_iface_ids,
                stateful=stateful,
                tags=tags,
                metadata={
                    "vm_id": vm.get("vm_id", ""),
                    "guid": vm.get("guid", ""),
                    "generation": vm.get("generation", 1),
                    "state": vm.get("state", ""),
                    "dynamic_memory": memory_info.get("dynamic_enabled", False),
                    "memory_min_mb": memory_info.get("minimum_mb", 0),
                    "memory_max_mb": memory_info.get("maximum_mb", 0),
                    "cpu_reservation_mhz": cpu_info.get("reservation_mhz", 0),
                    "cpu_weight": cpu_info.get("relative_weight", 100),
                    "checkpoints": vm.get("checkpoints", []),
                    "checkpoint_count": len(vm.get("checkpoints", [])),
                    "replication_enabled": replication.get("enabled", False),
                    "replication_mode": replication.get("mode"),
                    "replication_state": replication.get("state"),
                    "replica_server": replication.get("replica_server"),
                    "replication_frequency_seconds": replication.get("frequency_seconds"),
                    "cluster_name": cluster_info.get("name"),
                    "cluster_node": cluster_info.get("node"),
                    "highly_available": cluster_info.get("highly_available", False),
                    "scvmm_cloud": scvmm.get("cloud"),
                    "scvmm_template": scvmm.get("service_template"),
                    "scvmm_properties": scvmm.get("custom_properties", {}),
                },
            )

            # Back-populate attached_to on storage volumes
            for vol in storage:
                if vol.id in disk_ids:
                    vol.attached_to = cr.id

            # Build dependencies: VM depends on its networks
            for net_id in net_iface_ids:
                cr.dependencies.append(
                    ResourceDependency(
                        source_id=cr.id,
                        target_id=net_id,
                        dependency_type=DependencyType.NETWORK,
                        description=f"VM {vm_name} connected to network",
                    )
                )

            results.append(cr)
        return results

    def _normalize_vswitches(self, vswitches: list[dict]) -> list[NetworkSegment]:
        """Map Hyper-V virtual switches to NetworkSegment."""
        results: list[NetworkSegment] = []
        for vs in vswitches:
            results.append(
                NetworkSegment(
                    name=vs.get("name", "unknown"),
                    platform=self.platform_name,
                    type=NetworkType.VSWITCH,
                    cidr=vs.get("subnet", "0.0.0.0/0"),
                    gateway=vs.get("gateway", ""),
                    vlan_id=vs.get("vlan_id"),
                    zone=vs.get("description", "").lower(),
                    tags={"type": vs.get("type", ""), "switch_type": vs.get("switch_type", "")},
                    metadata={
                        "switch_type": vs.get("switch_type", ""),
                        "bandwidth_mode": vs.get("bandwidth_mode", ""),
                        "description": vs.get("description", ""),
                        "connected_adapters": vs.get("connected_adapters", 0),
                        "host": vs.get("host", ""),
                    },
                )
            )
        return results

    def _normalize_storage(self, vms: list[dict]) -> list[StorageVolume]:
        """Extract VHD/VHDX data disks from VMs (skip boot disk)."""
        results: list[StorageVolume] = []
        for vm in vms:
            vm_name = vm.get("name", "unknown")
            disks = vm.get("disks", [])
            cluster_node = vm.get("cluster", {}).get("node", "")

            for disk in disks[1:]:  # Skip first (boot) disk
                results.append(
                    StorageVolume(
                        name=disk.get("name", "unknown"),
                        platform=self.platform_name,
                        region=cluster_node.split(".")[0] if cluster_node else "",
                        type=StorageType.BLOCK,
                        size_gb=disk.get("max_size_gb", 0),
                        mount_point=disk.get("controller", ""),
                        tags=vm.get("tags", {}),
                        metadata={
                            "vm_name": vm_name,
                            "format": disk.get("format", ""),
                            "disk_type": disk.get("type", ""),
                            "current_size_gb": disk.get("current_size_gb", 0),
                            "path": disk.get("path", ""),
                        },
                    )
                )
        return results

    def _normalize_firewalls(
        self,
        firewalls: list[dict],
        compute: list[ComputeResource],
    ) -> list[SecurityPolicy]:
        """Map Hyper-V / Windows firewall rules to SecurityPolicy."""
        results: list[SecurityPolicy] = []
        for fw in firewalls:
            rules: list[SecurityRule] = []
            for rule in fw.get("rules", []):
                protocol_raw = rule.get("protocol", "all").lower()
                try:
                    protocol = ProtocolType(protocol_raw)
                except ValueError:
                    protocol = ProtocolType.ALL

                port = rule.get("port")
                port_range = rule.get("port_range", "")
                action = "allow" if rule.get("action", "permit") == "permit" else "deny"

                rules.append(
                    SecurityRule(
                        source=rule.get("source", "0.0.0.0/0"),
                        destination=rule.get("destination", "0.0.0.0/0"),
                        port=port,
                        port_range=port_range if port_range else "",
                        protocol=protocol,
                        action=action,
                        direction="inbound",
                        priority=rule.get("order", 0),
                    )
                )

            applied_to = [cr.id for cr in compute]

            results.append(
                SecurityPolicy(
                    name=fw.get("name", "unknown"),
                    platform=self.platform_name,
                    type=SecurityPolicyType.FIREWALL,
                    rules=rules,
                    applied_to=applied_to,
                    metadata={"firewall_id": fw.get("id", "")},
                )
            )
        return results
