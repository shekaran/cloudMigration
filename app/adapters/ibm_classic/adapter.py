"""IBM Classic Infrastructure adapter — discovers VSIs, VLANs, and firewall rules."""

from typing import Any
from uuid import UUID

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
    SecurityPolicyType,
    SecurityRule,
    StorageVolume,
    StorageType,
)
from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


def _parse_tags(tag_refs: list[dict]) -> dict[str, str]:
    """Convert SoftLayer tag references to key-value dict.

    Handles both 'key:value' format and plain tags.
    """
    tags: dict[str, str] = {}
    for ref in tag_refs:
        tag_name = ref.get("tag", {}).get("name", "")
        if ":" in tag_name:
            key, value = tag_name.split(":", 1)
            tags[key] = value
        elif tag_name:
            tags[tag_name] = ""
    return tags


class IBMClassicAdapter(AbstractBaseAdapter):
    """Adapter for IBM Classic Infrastructure (SoftLayer)."""

    @property
    def platform_name(self) -> str:
        return "ibm_classic"

    async def discover(self) -> dict[str, Any]:
        """Return mocked IBM Classic API data."""
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

        networks = self._normalize_vlans(raw_data.get("vlans", []))
        storage = self._normalize_storage(raw_data.get("virtual_servers", []))
        compute = self._normalize_virtual_servers(
            raw_data.get("virtual_servers", []), networks, storage
        )
        security_policies = self._normalize_firewalls(
            raw_data.get("firewalls", []), compute, networks
        )

        # Link security_groups on compute resources
        for vm in compute:
            vm.security_groups = [sp.id for sp in security_policies]

        # Link connected_resources on networks
        network_id_by_vlan = {n.vlan_id: n.id for n in networks if n.vlan_id is not None}
        for vm in compute:
            for raw_vsi in raw_data.get("virtual_servers", []):
                if raw_vsi["hostname"] == vm.name:
                    for raw_vlan in raw_vsi.get("networkVlans", []):
                        net_id = network_id_by_vlan.get(raw_vlan["vlanNumber"])
                        if net_id:
                            # Add VM to network's connected_resources
                            for net in networks:
                                if net.id == net_id and vm.id not in net.connected_resources:
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

    def _normalize_virtual_servers(
        self,
        vsis: list[dict],
        networks: list[NetworkSegment],
        storage: list[StorageVolume],
    ) -> list[ComputeResource]:
        """Map SoftLayer VSI objects to ComputeResource."""
        network_id_by_vlan = {n.vlan_id: n.id for n in networks if n.vlan_id is not None}

        # Build storage UUID lookup: hostname → list of StorageVolume UUIDs
        storage_by_host: dict[str, list[UUID]] = {}
        for vol in storage:
            hostname = vol.metadata.get("hostname", "")
            storage_by_host.setdefault(hostname, []).append(vol.id)

        results: list[ComputeResource] = []
        for vsi in vsis:
            os_desc = (
                vsi.get("operatingSystem", {})
                .get("softwareLicense", {})
                .get("softwareDescription", {})
            )
            os_ref_code = os_desc.get("referenceCode", "unknown").lower()
            os_image = os_desc.get("name", "")

            ip_addresses = []
            if vsi.get("primaryIpAddress"):
                ip_addresses.append(vsi["primaryIpAddress"])
            if vsi.get("primaryBackendIpAddress"):
                ip_addresses.append(vsi["primaryBackendIpAddress"])

            tags = _parse_tags(vsi.get("tagReferences", []))

            root_disk_gb = 0
            block_devices = vsi.get("blockDevices", [])
            if block_devices:
                root_disk_gb = block_devices[0].get("diskImage", {}).get("capacity", 0)

            # Build network_interfaces UUIDs
            net_iface_ids: list[UUID] = []
            for raw_vlan in vsi.get("networkVlans", []):
                net_id = network_id_by_vlan.get(raw_vlan["vlanNumber"])
                if net_id:
                    net_iface_ids.append(net_id)

            hostname = vsi["hostname"]
            disk_ids = storage_by_host.get(hostname, [])

            # Determine statefulness from tier tag
            stateful = tags.get("tier") in ("db", "data")

            datacenter = vsi.get("datacenter", {}).get("name", "")

            vm = ComputeResource(
                name=hostname,
                platform=self.platform_name,
                region=datacenter,
                type=ComputeType.VM,
                cpu=vsi["maxCpu"],
                memory_gb=vsi["maxMemory"] // 1024,
                os=os_ref_code,
                image=os_image,
                storage_gb=root_disk_gb,
                ip_addresses=ip_addresses,
                disks=disk_ids,
                network_interfaces=net_iface_ids,
                stateful=stateful,
                tags=tags,
                metadata={
                    "classic_id": vsi["id"],
                    "datacenter": datacenter,
                    "fqdn": vsi.get("fullyQualifiedDomainName", ""),
                    "status": vsi.get("status", {}).get("keyName", ""),
                },
            )

            # Back-populate attached_to on storage volumes with VM UUID
            for vol in storage:
                if vol.id in disk_ids:
                    vol.attached_to = vm.id

            # Build dependencies: VM depends on its networks
            for net_id in net_iface_ids:
                vm.dependencies.append(
                    ResourceDependency(
                        source_id=vm.id,
                        target_id=net_id,
                        dependency_type=DependencyType.NETWORK,
                        description=f"VM {hostname} connected to network",
                    )
                )

            results.append(vm)
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
            network_space = vlan.get("networkSpace", "")
            results.append(
                NetworkSegment(
                    name=vlan.get("name", f"vlan-{vlan['vlanNumber']}"),
                    platform=self.platform_name,
                    region=vlan.get("primaryRouter", {}).get("hostname", "").split(".")[-1] if vlan.get("primaryRouter") else "",
                    type=NetworkType.VLAN,
                    cidr=cidr_str,
                    gateway=primary_subnet.get("gateway", ""),
                    vlan_id=vlan["vlanNumber"],
                    zone=network_space.lower(),
                    tags={"network_space": network_space},
                    metadata={
                        "classic_id": vlan["id"],
                        "network_space": network_space,
                        "router": vlan.get("primaryRouter", {}).get("hostname", ""),
                    },
                )
            )
        return results

    def _normalize_firewalls(
        self,
        firewalls: list[dict],
        compute: list[ComputeResource],
        networks: list[NetworkSegment],
    ) -> list[SecurityPolicy]:
        """Map SoftLayer firewall rules to SecurityPolicy (grouped model)."""
        results: list[SecurityPolicy] = []

        for fw in firewalls:
            rules: list[SecurityRule] = []
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

                rules.append(
                    SecurityRule(
                        source=f"{rule.get('sourceIpAddress', '0.0.0.0')}/{src_cidr}",
                        destination=f"{rule.get('destinationIpAddress', '0.0.0.0')}/{dst_cidr}",
                        port=port,
                        port_range=port_range,
                        protocol=protocol,
                        action=rule.get("action", "allow"),
                        direction="inbound",
                        priority=rule.get("orderValue", 0),
                    )
                )

            # applied_to: all compute and network resources protected by this firewall
            applied_ids: list[UUID] = [vm.id for vm in compute] + [n.id for n in networks]

            results.append(
                SecurityPolicy(
                    name=fw.get("name", f"firewall-{fw.get('id', 'unknown')}"),
                    platform=self.platform_name,
                    type=SecurityPolicyType.FIREWALL,
                    rules=rules,
                    applied_to=applied_ids,
                    metadata={
                        "firewall_id": fw["id"],
                    },
                )
            )
        return results

    def _normalize_storage(self, vsis: list[dict]) -> list[StorageVolume]:
        """Extract additional storage volumes from VSI block devices (skip boot disk)."""
        results: list[StorageVolume] = []
        for vsi in vsis:
            block_devices = vsi.get("blockDevices", [])
            for i, device in enumerate(block_devices[1:], start=1):
                disk = device.get("diskImage", {})
                results.append(
                    StorageVolume(
                        name=f"{vsi['hostname']}-{disk.get('name', 'disk')}",
                        platform=self.platform_name,
                        region=vsi.get("datacenter", {}).get("name", ""),
                        type=StorageType.BLOCK,
                        size_gb=disk.get("capacity", 0),
                        mount_point=f"/dev/xvd{chr(97 + i)}",
                        tags=_parse_tags(vsi.get("tagReferences", [])),
                        metadata={
                            "classic_vsi_id": vsi["id"],
                            "hostname": vsi["hostname"],
                        },
                    )
                )
        return results
