# Architecture: Multi-Platform Migration Orchestration Engine

---

# 1. Architectural Overview

This system is designed as a **modular, adapter-driven migration platform** that orchestrates the migration of workloads from heterogeneous environments into IBM Cloud VPC.

The architecture follows these principles:

* Adapter-based extensibility
* Canonical data modeling
* Separation of concerns
* Workflow-driven execution
* Infrastructure-as-Code generation

---

# 2. High-Level Architecture

## Logical Layers

1. Control Plane (API Layer)
2. Orchestration Layer
3. Adapter Layer
4. Canonical Model Layer
5. Core Services Layer
6. Infrastructure Layer (Terraform)
7. Execution Layer (Migration modules)

---

## Component Interaction Flow

1. User triggers migration via API
2. Adapter performs discovery
3. Data is normalized into canonical model
4. Dependency graph is built
5. Translation engine generates target model
6. Terraform is generated
7. Orchestrator executes workflows
8. Migration modules perform data movement
9. Validation and cutover executed

---

# 3. Core Components

---

## 3.1 API Layer (Control Plane)

### Responsibilities

* Expose REST endpoints
* Accept user requests
* Trigger workflows
* Return status

### Constraints

* Must be thin (no business logic)
* Delegates to services layer

---

## 3.2 Adapter Layer (Plugin System)

### Purpose

Encapsulate platform-specific logic.

### Design

Each adapter must implement:

* discover()
* normalize()
* translate()
* migrate()

---

### Supported Adapters (Implemented)

* IBM Classic Adapter — SoftLayer VSIs, VLANs, firewall rules, storage volumes
* VMware Adapter — vSphere VMs, vSwitches, NSX-T segments, DFW firewall rules
* Kubernetes Adapter — Deployments, StatefulSets, Services, PVCs, ConfigMaps

### Planned Adapters

* Hyper-V Adapter
* Bare Metal Adapter
* Firewall Adapter

---

### Key Rules

* Adapters must NOT depend on each other
* Adapters must output canonical model
* Adapters must simulate APIs initially (mock data)

---

## 3.3 Canonical Model Layer

### Purpose

Provide a unified representation of all resources.

---

### Core Entities

* ComputeResource
* NetworkSegment
* SecurityPolicy
* StorageVolume
* KubernetesResource

---

### Design Requirements

* Platform-agnostic
* Extensible
* Includes metadata
* Includes dependencies

---

### Example

```json
{
  "compute": {
    "type": "vm",
    "cpu": 4,
    "memory": 16,
    "platform": "vmware"
  }
}
```

---

## 3.4 Dependency Graph Engine

### Purpose

Determine execution order of resources.

---

### Responsibilities

* Build directed graph
* Identify dependencies
* Perform topological sorting
* Detect cycles

---

### Output

* Ordered execution plan

---

## 3.5 Translation Engine

### Purpose

Convert canonical model → target platform model.

Two translation paths exist:

1. **VM Translation** — Canonical → IBM VPC model (subnets, security groups, VSIs)
2. **K8s Translation** — Canonical → IKS or OpenShift model (workloads, services, storage)

---

### VM Translation Responsibilities

* Map compute resources → VPC instances (profile selection, OS image mapping)
* Map networking constructs → VPC subnets (CIDR allocation)
* Map security rules → VPC security groups (rule normalization)
* Apply migration strategy (lift_and_shift, replatform, rebuild)

### K8s Translation Responsibilities

* Map workloads → target Deployments/StatefulSets with platform-specific manifests
* Map services → target Services (OpenShift converts LoadBalancer → ClusterIP + Routes)
* Map PVCs → target storage with platform-specific storage class mapping
* Rewrite container image registries (IKS: `us.icr.io/migration`, OpenShift: internal registry)

---

### Key Transformations

| Source               | VM Target       | K8s Target              |
| -------------------- | --------------- | ----------------------- |
| VLAN / NSX / vSwitch | Subnet          | —                       |
| Firewall rules       | Security Groups | —                       |
| VM                   | VPC VSI         | —                       |
| Deployment           | —               | IKS/OpenShift Workload  |
| Service              | —               | IKS/OpenShift Service   |
| PVC                  | —               | IKS/OpenShift Storage   |

---

### Requirements

* CIDR allocation logic (VM path)
* Conflict detection
* Rule normalization
* Platform-specific storage class mapping (K8s path)
* Image registry rewriting (K8s path)

---

## 3.6 Terraform Generator

### Purpose

Generate Infrastructure-as-Code for target environment.

---

### Responsibilities

* Generate:

  * VPC
  * Subnets
  * Security groups
  * Compute instances

---

### Design

* Template-based (Jinja2)
* Modular Terraform structure
* No execution logic inside generator

---

## 3.7 Migration Strategy Engine

### Purpose

Decide how each workload should be migrated.

---

### Strategies

* `lift_and_shift` — direct migration with minimal changes (standard profiles)
* `replatform` — migration with platform optimization (memory-optimized profiles, larger volumes)
* `rebuild` — fresh provisioning (minimal instance, no data carried over)
* `kubernetes_migration` — routed to K8s pipeline (backup → translate → restore)

---

### Decision Inputs

* Resource type (VM, baremetal, container)
* Platform and OS complexity (Windows/SLES/AIX trigger replatform)
* Statefulness
* Dependency count (critical resources with 3+ dependents)
* CPU/memory sizing

---

## 3.7.1 Containerization Recommender

### Purpose

Evaluate VMs for containerization suitability (advisory only, does not change migration path).

### Scoring Factors (0-100)

* OS compatibility (+15 for Linux, -30 for Windows/AIX)
* Statefulness (+15 for stateless, -10 for stateful)
* Resource sizing (+10 for small, -5 for large)
* Tier classification (+10 for web tier, -5 for db tier)
* Storage complexity (-10 for >500GB)
* Bare metal (-20)

### Fitness Levels

* `EXCELLENT` (>=75) — strong containerization candidate
* `GOOD` (>=55) — viable with moderate effort
* `POSSIBLE` (>=35) — requires refactoring
* `NOT_RECOMMENDED` (<35 or blockers) — keep as VM

---

## 3.8 Workflow Orchestrator

### Engine

Temporal

---

### Responsibilities

* Execute workflows
* Manage state
* Retry failures
* Handle long-running tasks

---

### Workflows

* discovery
* normalization
* planning
* provisioning
* migration
* validation
* cutover

---

## 3.9 Execution Layer

### Components

* **Data Migration Module** — rsync-based VM data transfer with per-VM logs and disk inventories
* **Kubernetes Migration Module** — Velero-like backup/restore with PVC snapshots and restore validation
* **Firewall Translation Module** — rule normalization, conflict resolution (most-specific-wins), tier classification

---

### Kubernetes Migration Pipeline

1. **Backup** — capture workload specs, service specs, PVC snapshots → write to disk
2. **Translate** — generate target manifests (IKS or OpenShift) with platform-specific mappings
3. **Restore** — write translated manifests to target directory structure
4. **Validate** — 6 check types: namespace coverage, workload coverage, replica counts, PVC coverage, storage size, service coverage

---

### Responsibilities

* Perform actual migration steps
* Execute data transfer (VM) or manifest generation (K8s)
* Handle system-specific operations
* Validate migration completeness

---

# 4. Data Flow

## VM Pipeline Flow

1. API receives migration request
2. Adapter performs discovery (IBM Classic or VMware)
3. Data normalized into canonical model
4. Dependency graph constructed
5. Pre-migration validation (32 checks)
6. Strategy analysis + firewall analysis + network planning
7. Translation engine generates VPC target model
8. Terraform generated
9. Data migration executed (rsync simulation)
10. Containerization recommendations generated (advisory)

## K8s Pipeline Flow

1. API receives migration request
2. Kubernetes adapter discovers workloads
3. Data normalized into canonical model
4. Dependency graph constructed
5. Pre-migration validation
6. Strategy analysis
7. Backup created (workload specs + PVC snapshots)
8. K8s translation to IKS or OpenShift manifests
9. Restore manifests written to target directory
10. Restore validation (namespace, workload, PVC, service coverage)

---

# 5. Project Structure

/app
/api
/core
/adapters
/models
/services
/workflows
/terraform
/graph
/utils

---

# 6. Design Patterns Used

* Adapter Pattern (platform abstraction)
* Strategy Pattern (migration strategies)
* Factory Pattern (adapter instantiation)
* Dependency Injection
* Template Pattern (Terraform generation)

---

# 7. Key Architectural Constraints

* No tight coupling between modules
* No business logic in API layer
* Terraform generation must be isolated
* Canonical model must be central
* All workflows must be idempotent

---

# 8. Extensibility Model

To add a new platform:

1. Create new adapter
2. Implement base interface
3. Register adapter in plugin system
4. No changes required in core logic

---

# 9. Failure Handling Strategy

* Retry at workflow level
* Use compensation logic for rollback
* Log all failures with context

---

# 10. Observability

* Structured logging
* Workflow tracking
* Execution status API

---

# 11. Security Considerations

* No hardcoded credentials
* Use environment/config for secrets
* Mask sensitive data in logs

---

# 12. Scalability Considerations

* Stateless API layer
* Workflow-based execution
* Modular adapters

---

# 13. Future Evolution

* Multi-cloud support (AWS, Azure)
* Advanced network modeling
* Cost optimization engine
* UI dashboard

---

# 14. Summary

This system is a:

**Migration Control Plane + Execution Engine**

It is designed to be:

* Modular
* Extensible
* Platform-agnostic
* Production-ready

---

# 15. Phase 5.1 — Replication, Reliability & Usability

## 15.1 Replication Engine (`app/services/replication_engine.py`)

Handles continuous delta synchronization, parallel volume sync, and cutover optimization.

- **Continuous Delta Sync (CDC)**: Iterative block-level delta sync with convergence detection. Configurable sync interval, max iterations, and convergence threshold.
- **Parallel Sync**: Semaphore-controlled concurrent volume synchronization with priority scheduling (CRITICAL > HIGH > NORMAL > LOW).
- **Cutover Optimization**: Estimates downtime based on remaining delta, plans parallel cutover groups, and checks readiness against a max downtime target.

## 15.2 Reliability Layer (`app/services/reliability.py`)

Provides retry policies, idempotent execution, and compensation/rollback.

- **RetryPolicy**: Configurable max retries, exponential/linear/fixed backoff, per-error-type retryability.
- **IdempotencyTracker**: Deterministic operation keys, cached results, duplicate execution prevention.
- **ReliabilityManager**: Wraps any operation with retry + idempotency + compensation registration. Supports LIFO compensation execution for rollback.

## 15.3 Blueprint Engine (`app/blueprints/`)

Prebuilt migration templates and guided workflow engine.

- **YAML Templates**: 5 prebuilt templates (VMware lift-and-shift, IBM Classic replatform, K8s migration, bare metal rebuild, Hyper-V lift-and-shift). Auto-discovered from `app/blueprints/templates/`.
- **BlueprintEngine**: Template registry with filtering by category/platform, parameter validation, template variable resolution.
- **BlueprintInstance**: Configured instance with step-by-step execution tracking.

## 15.4 Data Model Additions (`app/models/replication.py`)

- **ReplicationState**: Per-resource replication lifecycle tracking with checksum verification.
- **ExecutionCheckpoint**: Workflow-level checkpoint with replication state snapshots for resume & recovery.
- **ChecksumRecord**: Per-volume/database SHA-256 integrity verification.

## 15.5 Updated Flow

```
Discovery → Canonical → Graph → Validation → Strategy → Translation → Terraform
    → Replication (Initial Sync → Continuous Delta Sync → Quiesce → Final Sync)
    → Checksum Validation → Cutover → Post-Cutover Validation
```

With reliability layer wrapping each phase: retry on transient failure, idempotent re-execution, compensation on unrecoverable failure.

---

# 16. Final Guideline

When implementing:

* Prioritize correctness over shortcuts
* Maintain clear separation of concerns
* Ensure every component is independently testable

---

