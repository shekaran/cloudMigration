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
        nsx_segments = raw_data.get("nsx_segments", [])
        nsx_rules = raw_data.get("nsx_firewall_rules", {})
        nsx_section_count = len(nsx_rules.get("sections", []))
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            vm_count=len(raw_data.get("virtual_machines", [])),
            vswitch_count=len(raw_data.get("vswitches", [])),
            nsx_segment_count=len(nsx_segments),
            nsx_firewall_sections=nsx_section_count,
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw vSphere data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        networks = self._normalize_vswitches(raw_data.get("vswitches", []))
        nsx_networks = self._normalize_nsx_segments(raw_data.get("nsx_segments", []))
        all_networks = networks + nsx_networks

        storage = self._normalize_storage(raw_data.get("virtual_machines", []))
        compute = self._normalize_vms(
            raw_data.get("virtual_machines", []), all_networks, storage
        )

        # Build vm_id → ComputeResource UUID lookup for NSX segment connected_vms
        vm_id_to_uuid = {}
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            vm_id_to_uuid[raw_vm.get("vm_id", "")] = vm.id

        # Link connected_resources on vSwitch networks
        network_by_name = {n.name: n.id for n in all_networks}
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            for iface in raw_vm.get("network", {}).get("interfaces", []):
                net_name = iface.get("network_name", "")
                net_id = network_by_name.get(net_name)
                if net_id:
                    for net in all_networks:
                        if net.id == net_id and vm.id not in net.connected_resources:
                            net.connected_resources.append(vm.id)

        # Link connected_resources on NSX segments using connected_vms
        nsx_seg_by_id = {}
        for seg, raw_seg in zip(nsx_networks, raw_data.get("nsx_segments", [])):
            nsx_seg_by_id[raw_seg.get("segment_id", "")] = seg
            for vm_id in raw_seg.get("connected_vms", []):
                vm_uuid = vm_id_to_uuid.get(vm_id)
                if vm_uuid and vm_uuid not in seg.connected_resources:
                    seg.connected_resources.append(vm_uuid)

        # Add NSX segment network interfaces to compute resources
        for vm, raw_vm in zip(compute, raw_data.get("virtual_machines", [])):
            vm_id = raw_vm.get("vm_id", "")
            for raw_seg in raw_data.get("nsx_segments", []):
                if vm_id in raw_seg.get("connected_vms", []):
                    seg_id = raw_seg.get("segment_id", "")
                    seg = nsx_seg_by_id.get(seg_id)
                    if seg and seg.id not in vm.network_interfaces:
                        vm.network_interfaces.append(seg.id)
                        vm.dependencies.append(
                            ResourceDependency(
                                source_id=vm.id,
                                target_id=seg.id,
                                dependency_type=DependencyType.NETWORK,
                                description=f"VM {vm.name} connected to NSX segment {seg.name}",
                            )
                        )

        # Normalize NSX distributed firewall rules
        security_policies = self._normalize_nsx_firewall(
            raw_data.get("nsx_firewall_rules", {}), compute, nsx_seg_by_id
        )

        # Link security groups to compute resources
        for vm in compute:
            for policy in security_policies:
                if vm.id in policy.applied_to and policy.id not in vm.security_groups:
                    vm.security_groups.append(policy.id)

        result = DiscoveredResources(
            compute=compute,
            networks=all_networks,
            security_policies=security_policies,
            storage=storage,
        )
        logger.info(
            "normalization_completed",
            platform=self.platform_name,
            total_resources=result.resource_count,
            nsx_segments=len(nsx_networks),
            security_policies=len(security_policies),
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

    def _normalize_nsx_segments(self, segments: list[dict]) -> list[NetworkSegment]:
        """Map NSX-T segment objects to NetworkSegment."""
        results: list[NetworkSegment] = []
        for seg in segments:
            subnet = seg.get("subnet", {})
            cidr = subnet.get("network", "0.0.0.0/0")
            gateway_raw = subnet.get("gateway_address", "")
            gateway = gateway_raw.split("/")[0] if "/" in gateway_raw else gateway_raw

            # Parse NSX tags into dict
            tags: dict[str, str] = {}
            for tag_entry in seg.get("tags", []):
                scope = tag_entry.get("scope", "")
                tag_val = tag_entry.get("tag", "")
                if scope:
                    tags[scope] = tag_val

            results.append(
                NetworkSegment(
                    name=seg.get("display_name", "unknown"),
                    platform=self.platform_name,
                    region="",
                    type=NetworkType.NSX_SEGMENT,
                    cidr=cidr,
                    gateway=gateway,
                    zone=tags.get("tier", ""),
                    tags=tags,
                    metadata={
                        "segment_id": seg.get("segment_id", ""),
                        "segment_type": seg.get("type", ""),
                        "transport_zone": seg.get("transport_zone", ""),
                        "description": seg.get("description", ""),
                        "dhcp_ranges": subnet.get("dhcp_ranges", []),
                        "security_zone": tags.get("zone", ""),
                    },
                )
            )
        return results

    def _normalize_nsx_firewall(
        self,
        firewall_data: dict,
        compute: list[ComputeResource],
        nsx_seg_by_id: dict[str, NetworkSegment],
    ) -> list[SecurityPolicy]:
        """Map NSX distributed firewall sections to SecurityPolicy models.

        Each DFW section becomes a SecurityPolicy with grouped rules.
        """
        if not firewall_data:
            return []

        results: list[SecurityPolicy] = []

        for section in firewall_data.get("sections", []):
            rules: list[SecurityRule] = []

            for rule in section.get("rules", []):
                if rule.get("disabled", False):
                    continue

                # Parse services → protocol + ports
                services = rule.get("services", [])
                if not services:
                    # Empty services = match all traffic
                    rules.append(self._build_nsx_rule(
                        rule, ProtocolType.ALL, None, "", nsx_seg_by_id
                    ))
                    continue

                for svc in services:
                    protocol_raw = svc.get("protocol", "ALL").lower()
                    try:
                        protocol = ProtocolType(protocol_raw)
                    except ValueError:
                        protocol = ProtocolType.ALL

                    ports = svc.get("destination_ports", [])
                    for port_str in ports:
                        if "-" in port_str:
                            rules.append(self._build_nsx_rule(
                                rule, protocol, None, port_str, nsx_seg_by_id
                            ))
                        else:
                            rules.append(self._build_nsx_rule(
                                rule, protocol, int(port_str), "", nsx_seg_by_id
                            ))

                    if not ports:
                        rules.append(self._build_nsx_rule(
                            rule, protocol, None, "", nsx_seg_by_id
                        ))

            # Determine applied_to from section scope
            applied_ids: list[UUID] = []
            scope_segments = section.get("rules", [{}])[0].get("scope", []) if section.get("rules") else []
            for scope_ref in scope_segments:
                seg = nsx_seg_by_id.get(scope_ref)
                if seg:
                    # Apply to all VMs connected to this segment
                    for vm in compute:
                        if seg.id in vm.network_interfaces and vm.id not in applied_ids:
                            applied_ids.append(vm.id)

            results.append(
                SecurityPolicy(
                    name=section.get("display_name", f"nsx-section-{section.get('section_id', '')}"),
                    platform=self.platform_name,
                    type=SecurityPolicyType.FIREWALL,
                    rules=rules,
                    applied_to=applied_ids,
                    metadata={
                        "section_id": section.get("section_id", ""),
                        "description": section.get("description", ""),
                        "stateful": section.get("stateful", True),
                        "category": firewall_data.get("category", ""),
                    },
                )
            )

        return results

    def _build_nsx_rule(
        self,
        raw_rule: dict,
        protocol: ProtocolType,
        port: int | None,
        port_range: str,
        nsx_seg_by_id: dict[str, NetworkSegment],
    ) -> SecurityRule:
        """Build a canonical SecurityRule from an NSX DFW rule."""
        # Resolve source/destination groups to CIDRs
        source = self._resolve_nsx_group(raw_rule.get("source_groups", []), nsx_seg_by_id)
        destination = self._resolve_nsx_group(raw_rule.get("destination_groups", []), nsx_seg_by_id)

        # Map NSX direction to canonical direction
        direction_map = {
            "IN": "inbound",
            "OUT": "outbound",
            "IN_OUT": "inbound",  # Expand to both directions at firewall engine level
        }
        direction = direction_map.get(raw_rule.get("direction", "IN"), "inbound")

        # Map NSX action
        action = "allow" if raw_rule.get("action", "ALLOW") == "ALLOW" else "deny"

        return SecurityRule(
            source=source,
            destination=destination,
            port=port,
            port_range=port_range,
            protocol=protocol,
            action=action,
            direction=direction,
            priority=raw_rule.get("sequence_number", 0),
        )

    @staticmethod
    def _resolve_nsx_group(
        groups: list[str], nsx_seg_by_id: dict[str, NetworkSegment]
    ) -> str:
        """Resolve NSX group references to CIDR. Returns first resolvable or 0.0.0.0/0."""
        for group in groups:
            if group == "ANY":
                return "0.0.0.0/0"
            seg = nsx_seg_by_id.get(group)
            if seg:
                return seg.cidr
        return "0.0.0.0/0"

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
