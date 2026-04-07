"""Realistic mock data simulating VMware vSphere API responses."""

VMWARE_MOCK_DATA: dict = {
    "virtual_machines": [
        {
            "vm_id": "vm-1001",
            "name": "webserver-prod-01",
            "power_state": "poweredOn",
            "guest": {
                "guest_id": "ubuntu64Guest",
                "guest_full_name": "Ubuntu Linux (64-bit)",
            },
            "config": {
                "num_cpu": 4,
                "memory_mb": 8192,
                "annotation": "Production web server",
                "uuid": "5021b53c-834e-7725-a222-b7d8f8e3001a",
            },
            "storage": {
                "disks": [
                    {"label": "Hard disk 1", "capacity_gb": 80, "thin_provisioned": True},
                    {"label": "Hard disk 2", "capacity_gb": 250, "thin_provisioned": False},
                ],
                "datastore": "datastore-prod-01",
            },
            "network": {
                "interfaces": [
                    {
                        "label": "Network adapter 1",
                        "mac_address": "00:50:56:8a:01:01",
                        "connected": True,
                        "network_name": "vSwitch-Prod-Web",
                        "ip_address": "192.168.10.11",
                    }
                ]
            },
            "runtime": {
                "host": "esxi-host-01.vsphere.local",
                "datacenter": "DC-Primary",
                "cluster": "Cluster-Prod",
                "resource_pool": "ResourcePool-Web",
            },
            "tags": ["env:production", "tier:web", "app:frontend"],
        },
        {
            "vm_id": "vm-1002",
            "name": "appserver-prod-01",
            "power_state": "poweredOn",
            "guest": {
                "guest_id": "centos8_64Guest",
                "guest_full_name": "CentOS 8 (64-bit)",
            },
            "config": {
                "num_cpu": 8,
                "memory_mb": 16384,
                "annotation": "Application server running Java services",
                "uuid": "5021b53c-834e-7725-a222-b7d8f8e3002b",
            },
            "storage": {
                "disks": [
                    {"label": "Hard disk 1", "capacity_gb": 100, "thin_provisioned": True},
                    {"label": "Hard disk 2", "capacity_gb": 500, "thin_provisioned": False},
                ],
                "datastore": "datastore-prod-01",
            },
            "network": {
                "interfaces": [
                    {
                        "label": "Network adapter 1",
                        "mac_address": "00:50:56:8a:02:01",
                        "connected": True,
                        "network_name": "vSwitch-Prod-App",
                        "ip_address": "192.168.20.11",
                    }
                ]
            },
            "runtime": {
                "host": "esxi-host-02.vsphere.local",
                "datacenter": "DC-Primary",
                "cluster": "Cluster-Prod",
                "resource_pool": "ResourcePool-App",
            },
            "tags": ["env:production", "tier:app", "app:backend"],
        },
        {
            "vm_id": "vm-1003",
            "name": "dbserver-prod-01",
            "power_state": "poweredOn",
            "guest": {
                "guest_id": "rhel8_64Guest",
                "guest_full_name": "Red Hat Enterprise Linux 8 (64-bit)",
            },
            "config": {
                "num_cpu": 16,
                "memory_mb": 32768,
                "annotation": "PostgreSQL primary database server",
                "uuid": "5021b53c-834e-7725-a222-b7d8f8e3003c",
            },
            "storage": {
                "disks": [
                    {"label": "Hard disk 1", "capacity_gb": 100, "thin_provisioned": True},
                    {"label": "Hard disk 2", "capacity_gb": 1000, "thin_provisioned": False},
                ],
                "datastore": "datastore-prod-02",
            },
            "network": {
                "interfaces": [
                    {
                        "label": "Network adapter 1",
                        "mac_address": "00:50:56:8a:03:01",
                        "connected": True,
                        "network_name": "vSwitch-Prod-App",
                        "ip_address": "192.168.20.12",
                    }
                ]
            },
            "runtime": {
                "host": "esxi-host-02.vsphere.local",
                "datacenter": "DC-Primary",
                "cluster": "Cluster-Prod",
                "resource_pool": "ResourcePool-DB",
            },
            "tags": ["env:production", "tier:db", "app:postgres"],
        },
    ],
    "vswitches": [
        {
            "name": "vSwitch-Prod-Web",
            "type": "standard",
            "num_ports": 128,
            "mtu": 1500,
            "subnet": "192.168.10.0/24",
            "gateway": "192.168.10.1",
            "port_groups": [
                {"name": "PG-Web-Prod", "vlan_id": 100, "active_ports": 12}
            ],
            "host": "esxi-host-01.vsphere.local",
        },
        {
            "name": "vSwitch-Prod-App",
            "type": "standard",
            "num_ports": 256,
            "mtu": 1500,
            "subnet": "192.168.20.0/24",
            "gateway": "192.168.20.1",
            "port_groups": [
                {"name": "PG-App-Prod", "vlan_id": 200, "active_ports": 24}
            ],
            "host": "esxi-host-02.vsphere.local",
        },
    ],
    "nsx_segments": [
        {
            "segment_id": "seg-web-prod",
            "display_name": "NSX-Web-Prod",
            "description": "Production web tier overlay segment",
            "type": "OVERLAY",
            "transport_zone": "tz-overlay-prod",
            "subnet": {
                "gateway_address": "10.10.10.1/24",
                "network": "10.10.10.0/24",
                "dhcp_ranges": ["10.10.10.100-10.10.10.200"],
            },
            "vlan_ids": [],
            "tags": [
                {"scope": "tier", "tag": "web"},
                {"scope": "env", "tag": "production"},
                {"scope": "zone", "tag": "dmz"},
            ],
            "connected_vms": ["vm-1001"],
            "status": "SUCCESS",
        },
        {
            "segment_id": "seg-app-prod",
            "display_name": "NSX-App-Prod",
            "description": "Production application tier overlay segment",
            "type": "OVERLAY",
            "transport_zone": "tz-overlay-prod",
            "subnet": {
                "gateway_address": "10.10.20.1/24",
                "network": "10.10.20.0/24",
                "dhcp_ranges": ["10.10.20.100-10.10.20.200"],
            },
            "vlan_ids": [],
            "tags": [
                {"scope": "tier", "tag": "app"},
                {"scope": "env", "tag": "production"},
                {"scope": "zone", "tag": "trusted"},
            ],
            "connected_vms": ["vm-1002"],
            "status": "SUCCESS",
        },
        {
            "segment_id": "seg-db-prod",
            "display_name": "NSX-DB-Prod",
            "description": "Production database tier overlay segment",
            "type": "OVERLAY",
            "transport_zone": "tz-overlay-prod",
            "subnet": {
                "gateway_address": "10.10.30.1/24",
                "network": "10.10.30.0/24",
                "dhcp_ranges": ["10.10.30.100-10.10.30.200"],
            },
            "vlan_ids": [],
            "tags": [
                {"scope": "tier", "tag": "db"},
                {"scope": "env", "tag": "production"},
                {"scope": "zone", "tag": "restricted"},
            ],
            "connected_vms": ["vm-1003"],
            "status": "SUCCESS",
        },
    ],
    "nsx_firewall_rules": {
        "category": "Application",
        "sections": [
            {
                "section_id": "dfw-section-web",
                "display_name": "Web-Tier-Rules",
                "description": "Distributed firewall rules for web tier",
                "stateful": True,
                "rules": [
                    {
                        "rule_id": "dfw-rule-1001",
                        "display_name": "Allow-HTTPS-Inbound",
                        "description": "Allow HTTPS from any to web tier",
                        "action": "ALLOW",
                        "direction": "IN",
                        "ip_protocol": "IPV4",
                        "source_groups": ["ANY"],
                        "destination_groups": ["seg-web-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["443"]},
                        ],
                        "scope": ["seg-web-prod"],
                        "sequence_number": 10,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:web",
                    },
                    {
                        "rule_id": "dfw-rule-1002",
                        "display_name": "Allow-HTTP-Inbound",
                        "description": "Allow HTTP from any to web tier",
                        "action": "ALLOW",
                        "direction": "IN",
                        "ip_protocol": "IPV4",
                        "source_groups": ["ANY"],
                        "destination_groups": ["seg-web-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["80"]},
                        ],
                        "scope": ["seg-web-prod"],
                        "sequence_number": 20,
                        "logged": False,
                        "disabled": False,
                        "tag": "tier:web",
                    },
                    {
                        "rule_id": "dfw-rule-1003",
                        "display_name": "Allow-Web-to-App",
                        "description": "Allow web tier to reach app tier on 8080",
                        "action": "ALLOW",
                        "direction": "OUT",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-web-prod"],
                        "destination_groups": ["seg-app-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["8080", "8443"]},
                        ],
                        "scope": ["seg-web-prod"],
                        "sequence_number": 30,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:web",
                    },
                ],
            },
            {
                "section_id": "dfw-section-app",
                "display_name": "App-Tier-Rules",
                "description": "Distributed firewall rules for app tier",
                "stateful": True,
                "rules": [
                    {
                        "rule_id": "dfw-rule-2001",
                        "display_name": "Allow-From-Web",
                        "description": "Allow inbound from web tier on 8080/8443",
                        "action": "ALLOW",
                        "direction": "IN",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-web-prod"],
                        "destination_groups": ["seg-app-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["8080", "8443"]},
                        ],
                        "scope": ["seg-app-prod"],
                        "sequence_number": 10,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:app",
                    },
                    {
                        "rule_id": "dfw-rule-2002",
                        "display_name": "Allow-App-to-DB",
                        "description": "Allow app tier to reach database on 5432",
                        "action": "ALLOW",
                        "direction": "OUT",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-app-prod"],
                        "destination_groups": ["seg-db-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["5432"]},
                        ],
                        "scope": ["seg-app-prod"],
                        "sequence_number": 20,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:app",
                    },
                    {
                        "rule_id": "dfw-rule-2003",
                        "display_name": "Deny-App-Direct-Internet",
                        "description": "Block app tier from direct internet access",
                        "action": "DROP",
                        "direction": "OUT",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-app-prod"],
                        "destination_groups": ["ANY"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["80", "443"]},
                        ],
                        "scope": ["seg-app-prod"],
                        "sequence_number": 100,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:app",
                    },
                ],
            },
            {
                "section_id": "dfw-section-db",
                "display_name": "DB-Tier-Rules",
                "description": "Distributed firewall rules for database tier",
                "stateful": True,
                "rules": [
                    {
                        "rule_id": "dfw-rule-3001",
                        "display_name": "Allow-From-App-PostgreSQL",
                        "description": "Allow inbound PostgreSQL from app tier",
                        "action": "ALLOW",
                        "direction": "IN",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-app-prod"],
                        "destination_groups": ["seg-db-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["5432"]},
                        ],
                        "scope": ["seg-db-prod"],
                        "sequence_number": 10,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:db",
                    },
                    {
                        "rule_id": "dfw-rule-3002",
                        "display_name": "Allow-DB-Replication",
                        "description": "Allow PostgreSQL replication between DB nodes",
                        "action": "ALLOW",
                        "direction": "IN_OUT",
                        "ip_protocol": "IPV4",
                        "source_groups": ["seg-db-prod"],
                        "destination_groups": ["seg-db-prod"],
                        "services": [
                            {"protocol": "TCP", "destination_ports": ["5432", "5433"]},
                        ],
                        "scope": ["seg-db-prod"],
                        "sequence_number": 20,
                        "logged": False,
                        "disabled": False,
                        "tag": "tier:db",
                    },
                    {
                        "rule_id": "dfw-rule-3003",
                        "display_name": "Deny-All-DB-Inbound",
                        "description": "Default deny for database tier",
                        "action": "DROP",
                        "direction": "IN",
                        "ip_protocol": "IPV4",
                        "source_groups": ["ANY"],
                        "destination_groups": ["seg-db-prod"],
                        "services": [],
                        "scope": ["seg-db-prod"],
                        "sequence_number": 1000,
                        "logged": True,
                        "disabled": False,
                        "tag": "tier:db",
                    },
                ],
            },
        ],
    },
}
