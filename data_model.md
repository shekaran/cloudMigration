# Data Model: Multi-Platform Migration Orchestration Engine

---

# 1. Purpose

This document defines the **canonical data model** used across the system.

All components MUST use this model:

* Adapters → normalize into this model
* Translation Engine → consume this model
* Graph Engine → build dependencies using this model
* Terraform Generator → generate infra from this model

This is the **single source of truth for all resource definitions**

---

# 2. Design Principles

* Platform-agnostic representation
* Strong typing and structure
* Extensible for future platforms
* Explicit dependency modeling
* Minimal redundancy
* Globally unique identifiers using UUID

---

# 3. ID Standard (MANDATORY)

All resource identifiers MUST follow:

* Type: UUID (string format)
* Standard: UUID v4
* Format: `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`

Example:

```
"550e8400-e29b-41d4-a716-446655440000"
```

---

# 4. Top-Level Structure

```json
{
  "metadata": {},
  "resources": {
    "compute": [],
    "network": [],
    "security": [],
    "storage": [],
    "kubernetes": []
  },
  "relationships": []
}
```

---

# 5. Common Fields (All Resources)

All resources inherit from `BaseResource` and include:

| Field        | Type                     | Default          | Description                                 |
| ------------ | ------------------------ | ---------------- | ------------------------------------------- |
| id           | UUID                     | auto-generated   | Unique identifier (UUID v4)                 |
| name         | string                   | required         | Resource name                               |
| platform     | string                   | required         | Source platform (vmware, ibm_classic, etc.)  |
| region       | string                   | ""               | Source region                                |
| tags         | dict[str, str]           | {}               | Key-value metadata                           |
| metadata     | dict                     | {}               | Platform-specific metadata                   |
| dependencies | list[ResourceDependency] | []               | Structured relationships to other resources  |
| created_at   | datetime                 | now (UTC)        | When this record was created                 |
| updated_at   | datetime                 | now (UTC)        | When this record was last updated            |

### ResourceDependency

| Field           | Type           | Description                                  |
| --------------- | -------------- | -------------------------------------------- |
| source_id       | UUID           | ID of the resource that depends on another   |
| target_id       | UUID           | ID of the resource being depended upon       |
| dependency_type | DependencyType | Category of the dependency                   |
| description     | string         | Human-readable explanation                   |

### DependencyType (enum)

* `network`
* `storage`
* `compute`
* `security`
* `runtime`

---

# 6. ComputeResource

## 6.1 Schema

```json
{
  "id": "UUID",
  "name": "string",
  "type": "vm | baremetal | container",
  "platform": "string",
  "region": "string",
  "cpu": "int",
  "memory_gb": "int",
  "os": "string",
  "image": "string",
  "storage_gb": "int",
  "ip_addresses": ["string"],
  "disks": ["UUID"],
  "network_interfaces": ["UUID"],
  "security_groups": ["UUID"],
  "stateful": "boolean",
  "tags": "dict[str, str]",
  "metadata": {}
}
```

## 6.2 Field Details

| Field              | Type       | Default | Description                                |
| ------------------ | ---------- | ------- | ------------------------------------------ |
| type               | ComputeType| required| vm, baremetal, or container                |
| cpu                | int (> 0)  | required| Number of vCPUs                            |
| memory_gb          | int (> 0)  | required| Memory in gigabytes                        |
| os                 | string     | required| Operating system (e.g. ubuntu-22.04)       |
| image              | string     | ""      | OS image reference                         |
| storage_gb         | int (>= 0) | 0      | Root disk size in GB                       |
| ip_addresses       | list[str]  | []      | Assigned IP addresses                      |
| disks              | list[UUID] | []      | UUIDs of attached StorageVolumes           |
| network_interfaces | list[UUID] | []      | UUIDs of connected NetworkSegments         |
| security_groups    | list[UUID] | []      | UUIDs of applied SecurityPolicies          |
| stateful           | boolean    | false   | Whether workload is stateful               |

---

## 6.3 Notes

* `type` determines migration strategy
* `stateful` impacts sequencing and downtime handling
* All references use UUID (no name-based linking)
* `memory_gb` uses explicit unit suffix for clarity

---

# 7. NetworkSegment

## 7.1 Schema

```json
{
  "id": "UUID",
  "name": "string",
  "platform": "string",
  "region": "string",
  "type": "vlan | vswitch | nsx_segment | subnet | vpc",
  "cidr": "string",
  "gateway": "string",
  "vlan_id": "int | null",
  "zone": "string",
  "connected_resources": ["UUID"],
  "tags": "dict[str, str]",
  "metadata": {}
}
```

## 7.2 Field Details

| Field               | Type          | Default | Description                                 |
| ------------------- | ------------- | ------- | ------------------------------------------- |
| type                | NetworkType   | required| vlan, vswitch, nsx_segment, subnet, or vpc  |
| cidr                | string        | required| CIDR block (e.g. 10.0.1.0/24)              |
| gateway             | string        | ""      | Gateway IP address                          |
| vlan_id             | int or null   | null    | VLAN tag number if applicable               |
| zone                | string        | ""      | Zone for tier classification                |
| connected_resources | list[UUID]    | []      | UUIDs of resources on this network          |

## 7.3 Notes

* `cidr` must be validated (RFC 4632)
* `zone` used for tier classification
* `vlan_id` is only populated for VLAN-type networks

---

# 8. SecurityPolicy

## 8.1 Schema

```json
{
  "id": "UUID",
  "name": "string",
  "platform": "string",
  "region": "string",
  "type": "firewall | security_group",
  "rules": [
    {
      "source": "string",
      "destination": "string",
      "port": "int | null",
      "port_range": "string",
      "protocol": "tcp | udp | icmp | all",
      "action": "allow | deny",
      "direction": "inbound | outbound",
      "priority": "int"
    }
  ],
  "applied_to": ["UUID"],
  "tags": "dict[str, str]",
  "metadata": {}
}
```

## 8.2 SecurityRule Field Details

| Field       | Type         | Default   | Description                              |
| ----------- | ------------ | --------- | ---------------------------------------- |
| source      | string       | required  | Source CIDR or resource reference         |
| destination | string       | required  | Destination CIDR or resource reference    |
| port        | int or null  | null      | Single port number (0-65535)             |
| port_range  | string       | ""        | Port range (e.g. "8080-8090")           |
| protocol    | ProtocolType | required  | tcp, udp, icmp, or all                   |
| action      | string       | "allow"   | allow or deny                            |
| direction   | string       | "inbound" | inbound or outbound                      |
| priority    | int          | 0         | Rule priority / ordering                 |

## 8.3 Notes

* Each SecurityPolicy is a **grouped model** — one policy contains multiple rules
* `port` is used for single ports; `port_range` for ranges (mutually exclusive)
* `direction` distinguishes inbound vs outbound rules
* Rule normalization required across vendors
* Unsupported constructs must be flagged

---

# 9. StorageVolume

## 9.1 Schema

```json
{
  "id": "UUID",
  "name": "string",
  "platform": "string",
  "region": "string",
  "type": "block | file | object",
  "size_gb": "int",
  "iops": "int | null",
  "attached_to": "UUID | null",
  "mount_point": "string",
  "tags": "dict[str, str]",
  "metadata": {}
}
```

## 9.2 Field Details

| Field       | Type         | Default | Description                                  |
| ----------- | ------------ | ------- | -------------------------------------------- |
| type        | StorageType  | required| block, file, or object                       |
| size_gb     | int (> 0)    | required| Volume size in gigabytes                     |
| iops        | int or null  | null    | Provisioned IOPS if applicable               |
| attached_to | UUID or null | null    | UUID of the compute resource this is attached to |
| mount_point | string       | ""      | Filesystem mount point                       |

---

# 10. KubernetesResource

## 10.1 Schema

```json
{
  "id": "UUID",
  "name": "string",
  "platform": "kubernetes",
  "kind": "deployment | service | ingress | pod",
  "namespace": "string",
  "spec": {},
  "replicas": "int | null",
  "dependencies": ["ResourceDependency"],
  "metadata": {}
}
```

## 10.2 Field Details

| Field     | Type        | Default   | Description                          |
| --------- | ----------- | --------- | ------------------------------------ |
| kind      | string      | required  | K8s resource kind (Deployment, etc.) |
| namespace | string      | "default" | Kubernetes namespace                 |
| spec      | dict        | {}        | Resource spec as raw dict            |
| replicas  | int or null | null      | Desired replica count                |

---

# 11. Relationships

## 11.1 Schema

Relationships are modeled as `ResourceDependency` objects on each resource's `dependencies` list:

```json
{
  "source_id": "UUID",
  "target_id": "UUID",
  "dependency_type": "network | storage | compute | security | runtime",
  "description": "string"
}
```

---

## 11.2 Notes

* All graph edges must reference UUIDs
* No implicit relationships allowed
* `dependency_type` categorizes the nature of the relationship by resource type

---

# 12. MigrationPlan

## 12.1 Schema

```json
{
  "plan_id": "UUID",
  "resources": ["UUID"],
  "execution_order": ["UUID"],
  "strategies": {
    "UUID": "lift_and_shift | replatform | rebuild | kubernetes_migration"
  },
  "status": "pending | running | completed | failed"
}
```

---

# 13. Validation Rules

## 13.1 Required Validations

* All IDs must be valid UUID v4
* No duplicate UUIDs
* All references must resolve to existing resources
* No circular dependencies
* Valid CIDR ranges
* Compute resources must have network mapping

---

## 13.2 Failure Handling

* Validation failures must block execution
* Errors must include resource UUID for traceability

---

# 14. Example (Simplified)

```json
{
  "resources": {
    "compute": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "vm",
        "cpu": 4,
        "memory_gb": 16,
        "os": "ubuntu-22.04",
        "image": "Ubuntu 22.04 LTS",
        "storage_gb": 80,
        "ip_addresses": ["192.168.1.10"],
        "disks": ["a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"],
        "network_interfaces": ["6fa459ea-ee8a-3ca4-894e-db77e160355e"],
        "security_groups": ["7fb560fb-ff9b-4db5-995f-ec88f271466f"],
        "stateful": false
      }
    ],
    "network": [
      {
        "id": "6fa459ea-ee8a-3ca4-894e-db77e160355e",
        "type": "vlan",
        "cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "vlan_id": 100,
        "zone": "web",
        "connected_resources": ["550e8400-e29b-41d4-a716-446655440000"]
      }
    ],
    "security": [
      {
        "id": "7fb560fb-ff9b-4db5-995f-ec88f271466f",
        "type": "firewall",
        "rules": [
          {
            "source": "0.0.0.0/0",
            "destination": "192.168.1.0/24",
            "port": 443,
            "port_range": "",
            "protocol": "tcp",
            "action": "allow",
            "direction": "inbound",
            "priority": 1
          }
        ],
        "applied_to": ["550e8400-e29b-41d4-a716-446655440000"]
      }
    ],
    "storage": [
      {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "type": "block",
        "size_gb": 250,
        "iops": null,
        "attached_to": "550e8400-e29b-41d4-a716-446655440000",
        "mount_point": "/dev/xvdb"
      }
    ]
  },
  "relationships": [
    {
      "source_id": "550e8400-e29b-41d4-a716-446655440000",
      "target_id": "6fa459ea-ee8a-3ca4-894e-db77e160355e",
      "dependency_type": "network",
      "description": "VM connected to VLAN"
    }
  ]
}
```

---

# 15. Extensibility Guidelines

To add new resource types:

1. Define schema using UUID identifiers
2. Add to `resources` section
3. Update adapters
4. Extend translation engine

---

# 16. Key Constraints

* All identifiers must be UUID (no exceptions)
* No name-based linking
* No platform-specific IDs in canonical model
* All relationships must use UUID references

---

# 17. Final Guideline

If a resource cannot be represented in this model:

Extend the model -- DO NOT bypass it

---
