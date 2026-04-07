"""Bare Metal adapter — discovers physical servers with RAID, BMC, GPU, and bonded NICs."""

from typing import Any
from uuid import UUID

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.adapters.bare_metal.mock_data import BARE_METAL_MOCK_DATA
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


def _parse_tags(tag_list: list[str]) -> dict[str, str]:
    """Convert 'key:value' tag strings to key-value dict."""
    tags: dict[str, str] = {}
    for tag in tag_list:
        if ":" in tag:
            key, value = tag.split(":", 1)
            tags[key] = value
        elif tag:
            tags[tag] = ""
    return tags


class BareMetalAdapter(AbstractBaseAdapter):
    """Adapter for bare metal server fleet discovery and normalization."""

    @property
    def platform_name(self) -> str:
        return "bare_metal"

    async def discover(self) -> dict[str, Any]:
        """Return mocked bare metal fleet management API data."""
        logger.info("discovery_started", platform=self.platform_name)
        raw_data = BARE_METAL_MOCK_DATA
        servers = raw_data.get("servers", [])
        gpu_count = sum(1 for s in servers if s.get("gpu"))
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            server_count=len(servers),
            network_count=len(raw_data.get("networks", [])),
            gpu_servers=gpu_count,
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw bare metal data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        networks = self._normalize_networks(raw_data.get("networks", []))
        storage = self._normalize_storage(raw_data.get("servers", []))
        compute = self._normalize_servers(
            raw_data.get("servers", []), networks, storage
        )
        security_policies = self._normalize_firewalls(
            raw_data.get("firewalls", []), compute
        )

        # Link security groups to compute
        for server in compute:
            for policy in security_policies:
                if server.id in policy.applied_to and policy.id not in server.security_groups:
                    server.security_groups.append(policy.id)

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
            servers=len(compute),
            raid_volumes=len(storage),
        )
        return result

    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Stub — full translation implemented via TranslationService."""
        return {"status": "not_implemented"}

    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Stub — full migration implemented via Orchestrator."""
        return {"status": "not_implemented"}

    # --- Private helpers ---

    def _normalize_servers(
        self,
        servers: list[dict],
        networks: list[NetworkSegment],
        storage: list[StorageVolume],
    ) -> list[ComputeResource]:
        """Map bare metal servers to ComputeResource (type=BAREMETAL)."""
        network_by_vlan: dict[int, UUID] = {}
        for net in networks:
            if net.vlan_id is not None:
                network_by_vlan[net.vlan_id] = net.id

        # Build storage UUID lookup: hostname → list of StorageVolume UUIDs
        storage_by_host: dict[str, list[UUID]] = {}
        for vol in storage:
            hostname = vol.metadata.get("hostname", "")
            storage_by_host.setdefault(hostname, []).append(vol.id)

        results: list[ComputeResource] = []
        for server in servers:
            os_info = server.get("os", {})
            cpu_info = server.get("cpu", {})
            location = server.get("location", {})
            tags = _parse_tags(server.get("tags", []))

            hostname = server.get("hostname", "unknown")

            # Collect IPs and network interface UUIDs
            ip_addresses: list[str] = []
            net_iface_ids: list[UUID] = []
            for iface in server.get("network", {}).get("interfaces", []):
                ip = iface.get("ip_address", "")
                if ip:
                    ip_addresses.append(ip)
                vlan_id = iface.get("vlan_id")
                if vlan_id is not None and vlan_id in network_by_vlan:
                    net_id = network_by_vlan[vlan_id]
                    if net_id not in net_iface_ids:
                        net_iface_ids.append(net_id)

            # Boot disk = first RAID array size
            raid_arrays = server.get("storage", {}).get("raid_arrays", [])
            boot_disk_gb = raid_arrays[0].get("size_gb", 0) if raid_arrays else 0

            disk_ids = storage_by_host.get(hostname, [])

            # Determine statefulness from tier
            stateful = tags.get("tier") in ("db", "data")

            # OS reference code
            os_ref = os_info.get("reference_code", os_info.get("name", "unknown"))

            cr = ComputeResource(
                name=hostname,
                platform=self.platform_name,
                region=location.get("datacenter", ""),
                type=ComputeType.BAREMETAL,
                cpu=cpu_info.get("total_cores", 1),
                memory_gb=server.get("memory_gb", 1),
                os=os_ref.lower(),
                image=f"{os_info.get('name', '')} {os_info.get('version', '')}",
                storage_gb=boot_disk_gb,
                ip_addresses=ip_addresses,
                disks=disk_ids,
                network_interfaces=net_iface_ids,
                stateful=stateful,
                tags=tags,
                metadata={
                    "server_id": server.get("server_id", ""),
                    "serial_number": server.get("serial_number", ""),
                    "manufacturer": server.get("manufacturer", ""),
                    "model": server.get("model", ""),
                    "bios_type": server.get("bios", {}).get("type", ""),
                    "bios_version": server.get("bios", {}).get("version", ""),
                    "secure_boot": server.get("bios", {}).get("secure_boot", False),
                    "bmc_type": server.get("bmc", {}).get("type", ""),
                    "bmc_ip": server.get("bmc", {}).get("ip_address", ""),
                    "cpu_model": cpu_info.get("model", ""),
                    "cpu_architecture": cpu_info.get("architecture", ""),
                    "cpu_sockets": cpu_info.get("sockets", 1),
                    "threads_per_core": cpu_info.get("threads_per_core", 1),
                    "power_state": server.get("power_state", ""),
                    "rack": location.get("rack", ""),
                    "rack_unit": location.get("unit", ""),
                    "raid_controller": server.get("storage", {}).get("controller", ""),
                    "nic_bonding": [
                        {
                            "name": iface.get("name"),
                            "mode": iface.get("mode"),
                            "slaves": iface.get("slaves", []),
                            "speed_gbps": iface.get("speed_gbps"),
                        }
                        for iface in server.get("network", {}).get("interfaces", [])
                        if iface.get("type") == "bond"
                    ],
                    "gpu": server.get("gpu"),
                },
            )

            # Back-populate attached_to on storage volumes
            for vol in storage:
                if vol.id in disk_ids:
                    vol.attached_to = cr.id

            # Build dependencies: server depends on its networks
            for net_id in net_iface_ids:
                cr.dependencies.append(
                    ResourceDependency(
                        source_id=cr.id,
                        target_id=net_id,
                        dependency_type=DependencyType.NETWORK,
                        description=f"Server {hostname} connected to network",
                    )
                )

            results.append(cr)

        return results

    def _normalize_networks(self, networks: list[dict]) -> list[NetworkSegment]:
        """Map bare metal VLANs to NetworkSegment."""
        results: list[NetworkSegment] = []
        for net in networks:
            results.append(
                NetworkSegment(
                    name=net.get("name", "unknown"),
                    platform=self.platform_name,
                    type=NetworkType.VLAN,
                    cidr=net.get("cidr", "0.0.0.0/0"),
                    gateway=net.get("gateway", ""),
                    vlan_id=net.get("vlan_id"),
                    zone=net.get("zone", ""),
                    tags={"zone": net.get("zone", "")},
                    metadata={
                        "description": net.get("description", ""),
                    },
                )
            )
        return results

    def _normalize_storage(self, servers: list[dict]) -> list[StorageVolume]:
        """Extract RAID array data volumes from servers (skip boot array)."""
        results: list[StorageVolume] = []
        for server in servers:
            hostname = server.get("hostname", "unknown")
            location = server.get("location", {})
            raid_arrays = server.get("storage", {}).get("raid_arrays", [])
            all_disks = server.get("storage", {}).get("disks", [])

            for raid in raid_arrays[1:]:  # Skip first (boot) array
                # Determine IOPS hint from disk type
                member_disks = raid.get("disks", [])
                disk_types = [
                    all_disks[i].get("type", "") for i in member_disks if i < len(all_disks)
                ]
                iops = None
                if "NVMe" in disk_types:
                    iops = 100000
                elif "SSD" in disk_types:
                    iops = 50000

                results.append(
                    StorageVolume(
                        name=f"{hostname}-{raid.get('name', 'vol')}",
                        platform=self.platform_name,
                        region=location.get("datacenter", ""),
                        type=StorageType.BLOCK,
                        size_gb=raid.get("size_gb", 0),
                        iops=iops,
                        mount_point=raid.get("mount_point", ""),
                        tags=_parse_tags(server.get("tags", [])),
                        metadata={
                            "hostname": hostname,
                            "raid_level": raid.get("level", ""),
                            "raid_state": raid.get("state", ""),
                            "member_disks": len(member_disks),
                            "disk_types": disk_types,
                            "controller": server.get("storage", {}).get("controller", ""),
                        },
                    )
                )
        return results

    def _normalize_firewalls(
        self,
        firewalls: list[dict],
        compute: list[ComputeResource],
    ) -> list[SecurityPolicy]:
        """Map bare metal firewall rules to SecurityPolicy."""
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

            # Apply to all compute resources (perimeter firewall)
            applied_to = [cr.id for cr in compute]

            results.append(
                SecurityPolicy(
                    name=fw.get("name", "unknown"),
                    platform=self.platform_name,
                    type=SecurityPolicyType.FIREWALL,
                    rules=rules,
                    applied_to=applied_to,
                    metadata={
                        "firewall_id": fw.get("id", ""),
                    },
                )
            )
        return results
