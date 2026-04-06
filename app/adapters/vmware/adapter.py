"""VMware vSphere adapter — discovers VMs and vSwitches."""

from typing import Any
from uuid import UUID

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


def _parse_tags(tag_list: list[str]) -> dict[str, str]:
    """Convert VMware 'key:value' tag strings to key-value dict."""
    tags: dict[str, str] = {}
    for tag in tag_list:
        if ":" in tag:
            key, value = tag.split(":", 1)
            tags[key] = value
        elif tag:
            tags[tag] = ""
    return tags


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

        networks = self._normalize_vswitches(raw_data.get("vswitches", []))
        storage = self._normalize_storage(raw_data.get("virtual_machines", []))
        compute = self._normalize_vms(
            raw_data.get("virtual_machines", []), networks, storage
        )

        # Link connected_resources on networks
        network_by_name = {n.name: n.id for n in networks}
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            for iface in raw_vm.get("network", {}).get("interfaces", []):
                net_name = iface.get("network_name", "")
                net_id = network_by_name.get(net_name)
                if net_id:
                    for net in networks:
                        if net.id == net_id and vm.id not in net.connected_resources:
                            net.connected_resources.append(vm.id)

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

    def _normalize_vms(
        self,
        vms: list[dict],
        networks: list[NetworkSegment],
        storage: list[StorageVolume],
    ) -> list[ComputeResource]:
        """Map vSphere VM objects to ComputeResource."""
        network_by_name = {n.name: n.id for n in networks}

        # Build storage UUID lookup: vm_name → list of StorageVolume UUIDs
        storage_by_vm: dict[str, list[UUID]] = {}
        for vol in storage:
            vm_name = vol.metadata.get("vm_name", "")
            storage_by_vm.setdefault(vm_name, []).append(vol.id)

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

            tags = _parse_tags(vm.get("tags", []))

            # Build network_interfaces UUIDs
            net_iface_ids: list[UUID] = []
            for iface in vm.get("network", {}).get("interfaces", []):
                net_name = iface.get("network_name", "")
                net_id = network_by_name.get(net_name)
                if net_id:
                    net_iface_ids.append(net_id)

            vm_name = vm.get("name", "unknown")
            disk_ids = storage_by_vm.get(vm_name, [])
            datacenter = runtime.get("datacenter", "")

            # Determine statefulness from tier tag
            stateful = tags.get("tier") in ("db", "data")

            cr = ComputeResource(
                name=vm_name,
                platform=self.platform_name,
                region=datacenter,
                type=ComputeType.VM,
                cpu=config.get("num_cpu", 1),
                memory_gb=config.get("memory_mb", 1024) // 1024,
                os=guest.get("guest_id", "unknown"),
                image=guest.get("guest_full_name", ""),
                storage_gb=root_disk_gb,
                ip_addresses=ip_addresses,
                disks=disk_ids,
                network_interfaces=net_iface_ids,
                stateful=stateful,
                tags=tags,
                metadata={
                    "vm_id": vm.get("vm_id", ""),
                    "uuid": config.get("uuid", ""),
                    "power_state": vm.get("power_state", ""),
                    "datacenter": datacenter,
                    "cluster": runtime.get("cluster", ""),
                    "host": runtime.get("host", ""),
                    "annotation": config.get("annotation", ""),
                },
            )

            # Back-populate attached_to on storage volumes with VM UUID
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
        """Map vSphere vSwitch objects to NetworkSegment."""
        results: list[NetworkSegment] = []
        for vs in vswitches:
            port_groups = vs.get("port_groups", [])
            vlan_id = port_groups[0].get("vlan_id") if port_groups else None
            host = vs.get("host", "")

            results.append(
                NetworkSegment(
                    name=vs.get("name", "unknown"),
                    platform=self.platform_name,
                    region=host.split(".")[-1] if host else "",
                    type=NetworkType.VSWITCH,
                    cidr=vs.get("subnet", "0.0.0.0/0"),
                    gateway=vs.get("gateway", ""),
                    vlan_id=vlan_id,
                    zone=port_groups[0].get("name", "").lower() if port_groups else "",
                    tags={"type": vs.get("type", "standard")},
                    metadata={
                        "vswitch_type": vs.get("type", ""),
                        "mtu": vs.get("mtu", 1500),
                        "num_ports": vs.get("num_ports", 0),
                        "host": host,
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
            datacenter = vm.get("runtime", {}).get("datacenter", "")
            vm_name = vm.get("name", "vm")
            for i, disk in enumerate(disks[1:], start=1):
                results.append(
                    StorageVolume(
                        name=f"{vm_name}-{disk.get('label', 'disk')}",
                        platform=self.platform_name,
                        region=datacenter,
                        type=StorageType.BLOCK,
                        size_gb=disk.get("capacity_gb", 0),
                        mount_point=f"/dev/sd{chr(97 + i)}",
                        tags=_parse_tags(vm.get("tags", [])),
                        metadata={
                            "vm_id": vm.get("vm_id", ""),
                            "vm_name": vm_name,
                            "thin_provisioned": disk.get("thin_provisioned", False),
                            "datastore": vm.get("storage", {}).get("datastore", ""),
                        },
                    )
                )
        return results
