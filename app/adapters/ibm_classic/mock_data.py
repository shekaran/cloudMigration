"""Realistic mock data simulating IBM Classic Infrastructure API responses."""

IBM_CLASSIC_MOCK_DATA: dict = {
    "virtual_servers": [
        {
            "id": 48201537,
            "hostname": "web-prod-01",
            "domain": "example.softlayer.com",
            "fullyQualifiedDomainName": "web-prod-01.example.softlayer.com",
            "maxCpu": 4,
            "maxMemory": 16384,
            "status": {"name": "Active", "keyName": "ACTIVE"},
            "operatingSystem": {
                "softwareLicense": {
                    "softwareDescription": {
                        "name": "Ubuntu",
                        "version": "22.04-64",
                        "referenceCode": "UBUNTU_22_04_64",
                    }
                }
            },
            "datacenter": {"name": "dal13", "longName": "Dallas 13"},
            "primaryIpAddress": "169.48.152.10",
            "primaryBackendIpAddress": "10.186.41.20",
            "blockDevices": [
                {"diskImage": {"capacity": 100, "name": "boot-disk"}},
                {"diskImage": {"capacity": 500, "name": "data-disk"}},
            ],
            "networkVlans": [
                {"id": 2910174, "vlanNumber": 1280, "networkSpace": "PRIVATE"},
                {"id": 2910176, "vlanNumber": 1281, "networkSpace": "PUBLIC"},
            ],
            "tagReferences": [
                {"tag": {"name": "env:production"}},
                {"tag": {"name": "tier:web"}},
            ],
        },
        {
            "id": 48201538,
            "hostname": "app-prod-01",
            "domain": "example.softlayer.com",
            "fullyQualifiedDomainName": "app-prod-01.example.softlayer.com",
            "maxCpu": 8,
            "maxMemory": 32768,
            "status": {"name": "Active", "keyName": "ACTIVE"},
            "operatingSystem": {
                "softwareLicense": {
                    "softwareDescription": {
                        "name": "CentOS",
                        "version": "8-64",
                        "referenceCode": "CENTOS_8_64",
                    }
                }
            },
            "datacenter": {"name": "dal13", "longName": "Dallas 13"},
            "primaryIpAddress": "169.48.152.11",
            "primaryBackendIpAddress": "10.186.41.21",
            "blockDevices": [
                {"diskImage": {"capacity": 100, "name": "boot-disk"}},
                {"diskImage": {"capacity": 1000, "name": "data-disk"}},
            ],
            "networkVlans": [
                {"id": 2910174, "vlanNumber": 1280, "networkSpace": "PRIVATE"},
            ],
            "tagReferences": [
                {"tag": {"name": "env:production"}},
                {"tag": {"name": "tier:app"}},
            ],
        },
        {
            "id": 48201539,
            "hostname": "db-prod-01",
            "domain": "example.softlayer.com",
            "fullyQualifiedDomainName": "db-prod-01.example.softlayer.com",
            "maxCpu": 16,
            "maxMemory": 65536,
            "status": {"name": "Active", "keyName": "ACTIVE"},
            "operatingSystem": {
                "softwareLicense": {
                    "softwareDescription": {
                        "name": "Red Hat Enterprise Linux",
                        "version": "8-64",
                        "referenceCode": "RHEL_8_64",
                    }
                }
            },
            "datacenter": {"name": "dal13", "longName": "Dallas 13"},
            "primaryIpAddress": "169.48.152.12",
            "primaryBackendIpAddress": "10.186.41.22",
            "blockDevices": [
                {"diskImage": {"capacity": 100, "name": "boot-disk"}},
                {"diskImage": {"capacity": 2000, "name": "data-disk"}},
            ],
            "networkVlans": [
                {"id": 2910174, "vlanNumber": 1280, "networkSpace": "PRIVATE"},
            ],
            "tagReferences": [
                {"tag": {"name": "env:production"}},
                {"tag": {"name": "tier:db"}},
            ],
        },
    ],
    "vlans": [
        {
            "id": 2910174,
            "vlanNumber": 1280,
            "name": "private-dal13",
            "networkSpace": "PRIVATE",
            "primaryRouter": {"hostname": "bcr01a.dal13"},
            "subnets": [
                {
                    "id": 1843291,
                    "networkIdentifier": "10.186.41.0",
                    "cidr": 24,
                    "subnetType": "PRIMARY",
                    "gateway": "10.186.41.1",
                }
            ],
            "firewallInterfaces": [],
        },
        {
            "id": 2910176,
            "vlanNumber": 1281,
            "name": "public-dal13",
            "networkSpace": "PUBLIC",
            "primaryRouter": {"hostname": "fcr01a.dal13"},
            "subnets": [
                {
                    "id": 1843295,
                    "networkIdentifier": "169.48.152.0",
                    "cidr": 28,
                    "subnetType": "PRIMARY",
                    "gateway": "169.48.152.1",
                }
            ],
            "firewallInterfaces": [],
        },
    ],
    "firewalls": [
        {
            "id": 91234,
            "name": "vlan-1280-fw",
            "rules": [
                {
                    "orderValue": 1,
                    "action": "permit",
                    "protocol": "tcp",
                    "sourceIpAddress": "0.0.0.0",
                    "sourceIpCidr": 0,
                    "destinationIpAddress": "10.186.41.0",
                    "destinationIpCidr": 24,
                    "destinationPortRangeStart": 443,
                    "destinationPortRangeEnd": 443,
                    "notes": "Allow HTTPS to private subnet",
                },
                {
                    "orderValue": 2,
                    "action": "permit",
                    "protocol": "tcp",
                    "sourceIpAddress": "10.186.41.0",
                    "sourceIpCidr": 24,
                    "destinationIpAddress": "10.186.41.0",
                    "destinationIpCidr": 24,
                    "destinationPortRangeStart": 5432,
                    "destinationPortRangeEnd": 5432,
                    "notes": "Allow PostgreSQL within private subnet",
                },
            ],
        }
    ],
}
