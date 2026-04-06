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
}
