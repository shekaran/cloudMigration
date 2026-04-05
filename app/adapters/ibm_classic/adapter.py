"""IBM Classic Infrastructure adapter — discovers VSIs, VLANs, and firewall rules."""

from typing import Any

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.adapters.ibm_classic.mock_data import IBM_CLASSIC_MOCK_DATA
from app.models.canonical import (
    ComputeResource,
    ComputeType,
    NetworkSegment,
    NetworkType,
    ProtocolType,
    SecurityPolicy,
    StorageVolume,
    StorageType,
)
from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class IBMClassicAdapter(AbstractBaseAdapter):
    """Adapter for IBM Classic Infrastructure (SoftLayer)."""

    @property
    def platform_name(self) -> str:
        return "ibm_classic"

    async def discover(self) -> dict[str, Any]:
        """Return mocked IBM Classic API data.

        In production this would call the SoftLayer API.
        """
        logger.info("discovery_started", platform=self.platform_name)
        raw_data = IBM_CLASSIC_MOCK_DATA
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            vsi_count=len(raw_data.get("virtual_servers", [])),
            vlan_count=len(raw_data.get("vlans", [])),
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw SoftLayer data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        compute = self._normalize_virtual_servers(raw_data.get("virtual_servers", []))
        networks = self._normalize_vlans(raw_data.get("vlans", []))
        security_policies = self._normalize_firewalls(raw_data.get("firewalls", []))
        storage = self._normalize_storage(raw_data.get("virtual_servers", []))

        # Build cross-resource dependencies: VMs depend on their VLANs
        network_id_by_vlan = {n.vlan_id: n.id for n in networks if n.vlan_id is not None}
        for vm, raw_vsi in zip(compute, raw_data.get("virtual_servers", [])):
            for raw_vlan in raw_vsi.get("networkVlans", []):
                net_id = network_id_by_vlan.get(raw_vlan["vlanNumber"])
                if net_id:
                    vm.dependencies.append(
                        ResourceDependency(
                            source_id=vm.id,
                            target_id=net_id,
                            dependency_type=DependencyType.NETWORK,
                            description=f"VM {vm.name} connected to VLAN {raw_vlan['vlanNumber']}",
                        )
                    )

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
        )
        return result

    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Stub — full translation implemented in Phase 1."""
        logger.info("translate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_1"}

    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Stub — full migration implemented in Phase 1."""
        logger.info("migrate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_1"}

    # --- Private helpers ---

    def _normalize_virtual_servers(self, vsis: list[dict]) -> list[ComputeResource]:
        """Map SoftLayer VSI objects to ComputeResource."""
        results: list[ComputeResource] = []
        for vsi in vsis:
            os_desc = (
                vsi.get("operatingSystem", {})
                .get("softwareLicense", {})
                .get("softwareDescription", {})
            )
            os_name = os_desc.get("referenceCode", "unknown").lower()

            ip_addresses = []
            if vsi.get("primaryIpAddress"):
                ip_addresses.append(vsi["primaryIpAddress"])
            if vsi.get("primaryBackendIpAddress"):
                ip_addresses.append(vsi["primaryBackendIpAddress"])

            tags = [ref["tag"]["name"] for ref in vsi.get("tagReferences", [])]

            root_disk_gb = 0
            block_devices = vsi.get("blockDevices", [])
            if block_devices:
                root_disk_gb = block_devices[0].get("diskImage", {}).get("capacity", 0)

            results.append(
                ComputeResource(
                    name=vsi["hostname"],
                    platform=self.platform_name,
                    type=ComputeType.VM,
                    cpu=vsi["maxCpu"],
                    memory_gb=vsi["maxMemory"] // 1024,
                    os=os_name,
                    storage_gb=root_disk_gb,
                    ip_addresses=ip_addresses,
                    tags=tags,
                    metadata={
                        "classic_id": vsi["id"],
                        "datacenter": vsi.get("datacenter", {}).get("name", ""),
                        "fqdn": vsi.get("fullyQualifiedDomainName", ""),
                        "status": vsi.get("status", {}).get("keyName", ""),
                    },
                )
            )
        return results

    def _normalize_vlans(self, vlans: list[dict]) -> list[NetworkSegment]:
        """Map SoftLayer VLAN objects to NetworkSegment."""
        results: list[NetworkSegment] = []
        for vlan in vlans:
            subnets = vlan.get("subnets", [])
            primary_subnet = subnets[0] if subnets else {}
            cidr_str = (
                f"{primary_subnet.get('networkIdentifier', '0.0.0.0')}"
                f"/{primary_subnet.get('cidr', 0)}"
            )
            results.append(
                NetworkSegment(
                    name=vlan.get("name", f"vlan-{vlan['vlanNumber']}"),
                    platform=self.platform_name,
                    type=NetworkType.VLAN,
                    cidr=cidr_str,
                    gateway=primary_subnet.get("gateway", ""),
                    vlan_id=vlan["vlanNumber"],
                    metadata={
                        "classic_id": vlan["id"],
                        "network_space": vlan.get("networkSpace", ""),
                        "router": vlan.get("primaryRouter", {}).get("hostname", ""),
                    },
                )
            )
        return results

    def _normalize_firewalls(self, firewalls: list[dict]) -> list[SecurityPolicy]:
        """Map SoftLayer firewall rules to SecurityPolicy."""
        results: list[SecurityPolicy] = []
        for fw in firewalls:
            for rule in fw.get("rules", []):
                src_cidr = rule.get("sourceIpCidr", 0)
                dst_cidr = rule.get("destinationIpCidr", 0)
                protocol_raw = rule.get("protocol", "all").lower()
                try:
                    protocol = ProtocolType(protocol_raw)
                except ValueError:
                    protocol = ProtocolType.ALL

                port_start = rule.get("destinationPortRangeStart")
                port_end = rule.get("destinationPortRangeEnd")
                has_ports = port_start is not None and port_end is not None
                port = port_start if has_ports and port_start == port_end else None
                port_range = (
                    f"{port_start}-{port_end}"
                    if has_ports and port_start != port_end
                    else ""
                )

                results.append(
                    SecurityPolicy(
                        name=rule.get("notes", f"rule-{rule.get('orderValue', 0)}"),
                        platform=self.platform_name,
                        source=f"{rule.get('sourceIpAddress', '0.0.0.0')}/{src_cidr}",
                        destination=f"{rule.get('destinationIpAddress', '0.0.0.0')}/{dst_cidr}",
                        port=port,
                        port_range=port_range,
                        protocol=protocol,
                        action=rule.get("action", "allow"),
                        direction="inbound",
                        metadata={
                            "firewall_id": fw["id"],
                            "firewall_name": fw.get("name", ""),
                            "order_value": rule.get("orderValue"),
                        },
                    )
                )
        return results

    def _normalize_storage(self, vsis: list[dict]) -> list[StorageVolume]:
        """Extract additional storage volumes from VSI block devices (skip boot disk)."""
        results: list[StorageVolume] = []
        for vsi in vsis:
            block_devices = vsi.get("blockDevices", [])
            for device in block_devices[1:]:  # skip boot disk at index 0
                disk = device.get("diskImage", {})
                results.append(
                    StorageVolume(
                        name=f"{vsi['hostname']}-{disk.get('name', 'disk')}",
                        platform=self.platform_name,
                        type=StorageType.BLOCK,
                        size_gb=disk.get("capacity", 0),
                        attached_to=str(vsi.get("id", "")),
                        metadata={
                            "classic_vsi_id": vsi["id"],
                            "hostname": vsi["hostname"],
                        },
                    )
                )
        return results
