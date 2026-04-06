"""VMware vSphere adapter — discovers VMs and vSwitches."""

from typing import Any

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.adapters.vmware.mock_data import VMWARE_MOCK_DATA
from app.models.canonical import (
    ComputeResource,
    ComputeType,
    NetworkSegment,
    NetworkType,
    StorageVolume,
    StorageType,
)
from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class VMwareAdapter(AbstractBaseAdapter):
    """Adapter for VMware vSphere (basic VM + vSwitch discovery)."""

    @property
    def platform_name(self) -> str:
        return "vmware"

    async def discover(self) -> dict[str, Any]:
        """Return mocked vSphere API data."""
        logger.info("discovery_started", platform=self.platform_name)
        raw_data = VMWARE_MOCK_DATA
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            vm_count=len(raw_data.get("virtual_machines", [])),
            vswitch_count=len(raw_data.get("vswitches", [])),
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw vSphere data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        compute = self._normalize_vms(raw_data.get("virtual_machines", []))
        networks = self._normalize_vswitches(raw_data.get("vswitches", []))
        storage = self._normalize_storage(raw_data.get("virtual_machines", []))

        # Build dependencies: VMs depend on the vSwitch they're connected to
        network_by_name = {n.name: n.id for n in networks}
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            for iface in raw_vm.get("network", {}).get("interfaces", []):
                net_name = iface.get("network_name", "")
                net_id = network_by_name.get(net_name)
                if net_id:
                    vm.dependencies.append(
                        ResourceDependency(
                            source_id=vm.id,
                            target_id=net_id,
                            dependency_type=DependencyType.NETWORK,
                            description=f"VM {vm.name} connected to {net_name}",
                        )
                    )

        result = DiscoveredResources(
            compute=compute,
            networks=networks,
            storage=storage,
        )
        logger.info(
            "normalization_completed",
            platform=self.platform_name,
            total_resources=result.resource_count,
        )
        return result

    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Stub — full translation implemented via TranslationService."""
        logger.info("translate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_1"}

    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Stub — full migration implemented via Orchestrator."""
        logger.info("migrate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_1"}

    # --- Private helpers ---

    def _normalize_vms(self, vms: list[dict]) -> list[ComputeResource]:
        """Map vSphere VM objects to ComputeResource."""
        results: list[ComputeResource] = []
        for vm in vms:
            config = vm.get("config", {})
            guest = vm.get("guest", {})
            runtime = vm.get("runtime", {})

            ip_addresses = [
                iface["ip_address"]
                for iface in vm.get("network", {}).get("interfaces", [])
                if iface.get("ip_address")
            ]

            root_disk_gb = 0
            disks = vm.get("storage", {}).get("disks", [])
            if disks:
                root_disk_gb = disks[0].get("capacity_gb", 0)

            results.append(
                ComputeResource(
                    name=vm.get("name", "unknown"),
                    platform=self.platform_name,
                    type=ComputeType.VM,
                    cpu=config.get("num_cpu", 1),
                    memory_gb=config.get("memory_mb", 1024) // 1024,
                    os=guest.get("guest_id", "unknown"),
                    storage_gb=root_disk_gb,
                    ip_addresses=ip_addresses,
                    tags=vm.get("tags", []),
                    metadata={
                        "vm_id": vm.get("vm_id", ""),
                        "uuid": config.get("uuid", ""),
                        "power_state": vm.get("power_state", ""),
                        "datacenter": runtime.get("datacenter", ""),
                        "cluster": runtime.get("cluster", ""),
                        "host": runtime.get("host", ""),
                        "annotation": config.get("annotation", ""),
                    },
                )
            )
        return results

    def _normalize_vswitches(self, vswitches: list[dict]) -> list[NetworkSegment]:
        """Map vSphere vSwitch objects to NetworkSegment."""
        results: list[NetworkSegment] = []
        for vs in vswitches:
            port_groups = vs.get("port_groups", [])
            vlan_id = port_groups[0].get("vlan_id") if port_groups else None

            results.append(
                NetworkSegment(
                    name=vs.get("name", "unknown"),
                    platform=self.platform_name,
                    type=NetworkType.VSWITCH,
                    cidr=vs.get("subnet", "0.0.0.0/0"),
                    gateway=vs.get("gateway", ""),
                    vlan_id=vlan_id,
                    metadata={
                        "vswitch_type": vs.get("type", ""),
                        "mtu": vs.get("mtu", 1500),
                        "num_ports": vs.get("num_ports", 0),
                        "host": vs.get("host", ""),
                        "port_groups": [pg.get("name", "") for pg in port_groups],
                    },
                )
            )
        return results

    def _normalize_storage(self, vms: list[dict]) -> list[StorageVolume]:
        """Extract additional storage volumes from VM disks (skip boot disk)."""
        results: list[StorageVolume] = []
        for vm in vms:
            disks = vm.get("storage", {}).get("disks", [])
            for disk in disks[1:]:  # skip boot disk
                results.append(
                    StorageVolume(
                        name=f"{vm.get('name', 'vm')}-{disk.get('label', 'disk')}",
                        platform=self.platform_name,
                        type=StorageType.BLOCK,
                        size_gb=disk.get("capacity_gb", 0),
                        attached_to=vm.get("vm_id", ""),
                        metadata={
                            "vm_id": vm.get("vm_id", ""),
                            "thin_provisioned": disk.get("thin_provisioned", False),
                            "datastore": vm.get("storage", {}).get("datastore", ""),
                        },
                    )
                )
        return results
