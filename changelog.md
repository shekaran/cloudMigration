# Changelog

All notable changes to this project will be documented in this file.

---

## [0.6.0] - 2026-04-07 13:00 IST

### Phase 4 — Kubernetes & Modernization

Phase 4 adds Kubernetes workload migration (to IKS and OpenShift), a Velero-like backup/restore service, K8s manifest translation with platform-specific mappings, and a VM containerization recommender.

#### 1. Kubernetes Adapter (`app/adapters/kubernetes/`) — Issue #15

New adapter for discovering and normalizing Kubernetes workloads.

- **Mock data**: Multi-tier app — 3 Deployments/StatefulSets (web-frontend nginx, app-backend, postgres-db), 3 Services (LoadBalancer + ClusterIP), 2 ConfigMaps, 3 PVCs, 1 Secret, 1 HPA, 5-node cluster
- **Normalization**: Deployments/StatefulSets → `KubernetesResource` with full spec, container metadata, resource requests/limits
- **Cross-references**: Workloads → PVCs via volume mounts, workloads → services via selector match, app → db via env var dependency
- **Service mapping**: LoadBalancer → `NetworkSegment(type=VPC)`, ClusterIP → `NetworkSegment(type=SUBNET)`
- **PVC mapping**: PVCs → `StorageVolume` with storage class, access modes, size parsing
- **Network policies**: Generates implicit service-level `SecurityPolicy` for discovered services
- **Total resources**: 10 (3 workloads + 3 networks + 3 storage + 1 security policy)

#### 2. K8s Target Models (`app/models/k8s_target.py`) — Issue #16

Pydantic models for the K8s migration target.

- **`K8sTargetPlatform`** enum: `IKS`, `OPENSHIFT`
- **`K8sTargetCluster`**: name, platform, region, version, worker pool flavor, worker count
- **`K8sTargetWorkload`**: name, kind, namespace, replicas, full K8s manifest dict
- **`K8sTargetService`**: name, service type, ports, full manifest
- **`K8sTargetStorage`**: name, storage class, size, access modes, full manifest
- **`K8sTranslationResult`**: cluster + namespaces + workloads + services + storage

#### 3. K8s Translation Service (`app/services/k8s_translation.py`) — Issue #17

Translates discovered K8s resources to IKS or OpenShift target manifests.

- **Configurable target**: `target_platform="iks"` or `"openshift"` with platform-specific mappings
- **Storage class mapping**: Source classes mapped to IKS (`ibmc-vpc-block-*`) or OpenShift (`ocs-storagecluster-*`) equivalents
- **Image registry**: IKS (`us.icr.io/migration`) vs OpenShift (internal registry) — public images preserved, custom images prefixed
- **Service translation**: OpenShift converts `LoadBalancer` → `ClusterIP` (uses Routes instead)
- **Manifest generation**: Full K8s YAML manifests as dicts with `migrated-by: migration-engine` label
- **Namespace isolation**: Resources organized by source namespace

#### 4. K8s Backup/Restore Service (`app/services/k8s_migration.py`) — Issue #18

Velero-like backup and restore abstraction for Kubernetes migrations.

- **Backup**: Captures workload specs, service specs, config specs, PVC snapshots → writes to disk with unique backup ID
- **PVC snapshots**: Records storage class, size, access modes, bound status for each PVC
- **Restore**: Generates target manifests from backup + translation result → writes cluster.json, namespaces/, workloads/, services/, storage/ directory structure
- **Validation**: 6 check types — namespace coverage, workload coverage, replica counts, PVC coverage, storage size preservation, service coverage
- **Models**: `PVCSnapshot`, `KubernetesBackup`, `RestoreValidation` with pass/fail/warning counts

#### 5. Containerization Recommender (`app/services/containerization.py`) — Issue #19

Advisory service evaluating VMs for containerization fitness.

- **Multi-factor scoring** (0-100): OS compatibility (+15/-30), statefulness (+15/-10), resource sizing (+10/+5/-5), tier classification (+10/-5), storage complexity (-10/-5), bare metal (-20)
- **Fitness levels**: `EXCELLENT` (≥75), `GOOD` (≥55), `POSSIBLE` (≥35), `NOT_RECOMMENDED` (<35 or blockers)
- **Suggested approach**: Deployment vs StatefulSet, effort level (low/medium/high)
- **Blocker detection**: Windows/AIX OS, bare metal hardware, excessive storage (>500GB)
- **VMware results**: webserver=100 (excellent), appserver=85 (excellent), dbserver=45 (possible)

#### 6. Updated Pipeline & API

- **Dual pipeline**: Orchestrator routes to K8s pipeline (backup → translate → restore → validate) or VM pipeline based on adapter type
- **K8s pipeline steps**: discover → normalize → validate → analyze → k8s_backup → k8s_translate → k8s_restore → k8s_validate_restore
- **New `MigrationJob` fields**: `k8s_backup_id`, `k8s_workloads_migrated`, `k8s_target_platform`, `containerization_candidates`
- **New API endpoints**:
  - `POST /containerize/{adapter}` — VM containerization recommendations
  - `POST /k8s/backup/{adapter}` — K8s resource backup
  - `POST /k8s/translate/{adapter}?target_platform=iks|openshift` — K8s manifest translation
- **Updated endpoints**: `GET /status/{job_id}` includes K8s and containerization fields
- **Dependencies wiring**: K8sTranslationService, K8sMigrationService, ContainerizationRecommender added to DI container
- **Version**: 0.6.0

#### Validated
- 6/6 service tests passed (K8s translation IKS/OpenShift, backup/restore/validate, containerization recommender)
- 3/3 orchestrator pipeline tests passed (K8s pipeline, VMware backward compat, IBM Classic backward compat)
- 20/20 API endpoint tests passed (all 3 adapters, all Phase 1-4 endpoints including new containerize, k8s/backup, k8s/translate)
- K8s pipeline: 8 steps completed, 3 workloads migrated to IKS, backup/restore validation passed (10/10 checks)
- VMware backward compat: 7 steps completed, 2 containerization candidates detected
- IBM Classic backward compat: 7 steps completed, 9 resources migrated

#### References
- GitHub Issues: #15, #16, #17, #18, #19

---

## [0.5.0] - 2026-04-07 07:15 IST

### Phase 3 — Network & Security Expansion

Phase 3 adds VMware NSX-T support, a firewall translation engine with automatic conflict resolution, and tier-based network planning with configurable security zone mapping.

#### 1. VMware NSX-T Support (`app/adapters/vmware/`) — Issue #12

Extends the VMware adapter with NSX-T overlay segments and distributed firewall rules.

- **NSX segments**: 3 overlay segments (Web-Prod, App-Prod, DB-Prod) with CIDRs, DHCP ranges, security tags (tier + zone scope)
- **NSX distributed firewall**: 3 DFW sections (Web-Tier, App-Tier, DB-Tier) with 9 rules covering inter-tier traffic, deny rules, and replication
- **Normalization**: `_normalize_nsx_segments()` maps NSX segments to canonical `NetworkSegment` (type=`nsx_segment`) with tier/zone metadata
- **Firewall normalization**: `_normalize_nsx_firewall()` maps DFW sections to grouped `SecurityPolicy` models — resolves segment references to CIDRs, maps NSX actions (ALLOW/DROP) and directions (IN/OUT/IN_OUT)
- **Cross-resource linking**: NSX segments linked to VMs via `connected_vms`, VMs get NSX segment UUIDs in `network_interfaces` and `security_groups`
- **Discovery**: Logs NSX segment count and DFW section count alongside VM/vSwitch counts
- **Total VMware resources**: 8 → 14 (3 VMs + 2 vSwitches + 3 NSX segments + 3 security policies + 3 storage volumes)

#### 2. Firewall Translation Engine (`app/services/firewall_engine.py`) — Issue #13

Normalizes, analyzes, and resolves conflicts in firewall rules from heterogeneous sources.

- **Pipeline**: normalize → detect conflicts → resolve → consolidate → classify by tier
- **Rule normalization**: Flattens all `SecurityPolicy` rules into `NormalizedRule` format with validated CIDRs, protocols, ports, actions, directions, tier classification
- **Conflict detection**: Finds overlapping rules with contradictory actions — checks CIDR overlap, port overlap, protocol compatibility, direction match
- **Conflict resolution**:
  - `most_specific_wins` — higher CIDR prefix + specific port + specific protocol beats broader rules
  - `explicit_deny_wins` — deny takes precedence when specificity is equal
  - `unresolvable` — flagged for manual review when rules are equally specific with opposing actions
- **Consolidation**: Removes exact duplicate rules (same CIDR, protocol, port, action, direction)
- **Tier classification**: Groups rules by tier (web, app, db) inferred from policy name, policy tags, or rule metadata
- **Unsupported detection**: Flags rules with invalid CIDRs or unsupported protocols
- **VPC limits**: Tracks `MAX_RULES_PER_GROUP = 50` for security group rule count validation

#### 3. Tier-Based Network Planning (`app/services/network_planner.py`) — Issue #14

Enhances the network planner with tier-aware subnet allocation and configurable security zone mapping.

- **Tier classification priority**:
  1. Network's own tier tag (e.g., `tier:web` on NSX segment)
  2. Security zone metadata mapped via `zone_tier_map` (dmz→web, trusted→app, restricted→db)
  3. Tier inferred from connected compute resource tags (majority vote)
  4. Network zone field
- **Configurable zone → tier mapping**: `DEFAULT_ZONE_TIER_MAP` with override via `zone_tier_map` constructor parameter: `dmz→web`, `trusted→app`, `restricted→db`, `public→web`, `private→app`, `data→db`
- **Tier-grouped allocation**: Networks sorted by tier (web, app, db) then by prefix length — same-tier subnets grouped together with independent zone round-robin per tier
- **`SubnetAllocation` extended**: New `tier` and `security_zone` fields on each allocation
- **`TierAllocation` summary**: Per-tier totals (subnet count, host capacity, allocated CIDRs)
- **`NetworkPlan.tier_allocations`**: List of `TierAllocation` for tier-level reporting
- **Compute-aware**: `plan()` now accepts optional `compute` parameter for tier inference from VM tags
- **Backward compatible**: Phase 2 calls without `compute` parameter still work identically

#### 4. Updated Pipeline & API

- **Orchestrator pipeline enhanced**: Analyze step now runs firewall analysis alongside strategy and network planning
- **New `MigrationJob` fields**: `firewall_conflicts`, `firewall_rules_consolidated`, `tier_summary`
- **New API endpoint**:
  - `POST /firewall/{adapter}` — returns firewall analysis (normalized rules, conflicts with resolutions, unsupported rules, rules grouped by tier)
- **Updated endpoints**:
  - `POST /analyze/{adapter}` — now returns `firewall` analysis alongside `strategy` and `network_plan` with tier allocations
  - `GET /status/{job_id}` — now includes `firewall_conflicts`, `firewall_rules_consolidated`, `tier_summary`
- **`JobResponse` extended**: New fields for firewall and tier reporting
- **Dependencies wiring**: `FirewallEngine` added to DI container (`configure_services`, `get_firewall_engine`)

#### Validated
- 18/18 API endpoint tests passed (both adapters, all Phase 1 + Phase 2 + Phase 3 endpoints)
- Full pipeline: discover → normalize → validate → analyze (strategy + firewall + network) → translate → generate_terraform → migrate_data
- VMware: 14 resources discovered, 3 NSX segments, 3 security policies (13 firewall rules), 3 tiers (web/app/db), 3 conflicts auto-resolved
- IBM Classic: 9 resources, backward compatible (2 firewall rules, 0 conflicts)
- Tier-based allocation: web=2 subnets, app=2 subnets, db=1 subnet with correct security zone mapping

#### References
- GitHub Issues: #12, #13, #14

---

## [0.4.0] - 2026-04-06 23:15 IST

### Phase 2 — Orchestration & Intelligence

Phase 2 introduces reliability and execution intelligence — dependency-ordered migration, workload-aware strategy selection, pre-flight validation, and intelligent network allocation.

#### 1. Dependency Graph Engine (`app/graph/engine.py`) — Issue #9

Builds a directed acyclic graph from all resource dependencies (UUID-based edges).

- **Topological sort** (Kahn's algorithm) — determines correct execution order so dependencies are provisioned before dependents
- **Cycle detection** (DFS) — catches circular dependencies before they break execution, raises `CyclicDependencyError` with the cycle path
- **Parallel execution stages** — groups resources that can migrate concurrently (e.g., all networks in stage 0, all VMs in stage 1)
- **Graphviz DOT export** — color-coded visualization: blue=compute (box), green=network (ellipse), purple=storage (cylinder), orange=security (diamond). Edge styles vary by dependency type (solid=network, dashed=storage, dotted=security)
- **JSON export** — nodes with id/label/type, edges with source/target/type for API consumption

#### 2. Strategy Engine (`app/services/strategy.py`) — Issue #10

Classifies every resource into a migration strategy. **Strategy assignment changes actual translation output.**

- **Strategies**: `lift_and_shift`, `replatform`, `rebuild`, `kubernetes_migration`
- **Classification inputs**: resource type (VM/baremetal/container), statefulness, CPU/memory sizing, OS complexity (Windows/SLES/AIX trigger replatform), dependency count (critical resources with 3+ dependents)
- **Translation impact**:
  - `lift_and_shift` → standard `bx2-*` profiles, direct disk mapping
  - `replatform` → memory-optimized `mx2-*` profiles, 200GB+ boot volumes
  - `rebuild` → minimal fresh instance, no data volumes carried over
  - `kubernetes_migration` → flagged for container pipeline
- **Per-resource rationale** with risk level (low/medium/high) and estimated downtime (minimal/moderate/extended)
- Storage volumes inherit strategy from their attached compute resource

#### 3. Validation Engine (`app/services/validation.py`) — Issue #11

Runs 32 pre-migration checks with severity levels. **Default blocks execution on ERRORs.**

- **Compute checks**: OS compatibility against supported VPC images, CPU limit (max 64 vCPU), memory limit (max 256GB), NIC count (max 5), missing IP addresses
- **Network checks**: CIDR format validation (RFC 4632), duplicate CIDR detection, overlapping CIDR detection between networks
- **Security checks**: Rule count limit (max 50 per security group), unsupported protocol detection
- **Storage checks**: Volume size limit (max 16TB), orphaned volumes (not attached), invalid attachment references (dangling UUIDs)
- **Graph checks**: Cyclic dependency detection, isolated resource detection (no dependencies)
- **Reference integrity**: Validates all UUID cross-references (disks, network_interfaces) resolve to existing resources
- **Override**: `skip_validation=true` on `/execute` endpoint bypasses blocking — all errors collected and reported in job output

#### 4. Network Planner v1 (`app/services/network_planner.py`) — Issue #28

Allocates fresh target CIDRs instead of preserving source CIDRs (which may conflict or not fit the target VPC).

- **Target range**: Configurable VPC CIDR (default `10.240.0.0/16`)
- **Sizing preservation**: Keeps source prefix length (e.g., source `/24` → target `/24`) so host capacity matches
- **Sequential allocation**: Walks VPC address space finding first non-overlapping block for each subnet
- **Zone distribution**: Round-robin across availability zones (e.g., `us-south-1`, `us-south-2`, `us-south-3`)
- **Conflict detection**:
  - `overlap` — source networks with overlapping CIDRs (informational, target allocations are non-overlapping)
  - `exhaustion` — VPC address space too small for requested subnets
  - `sizing` — source subnet larger than VPC (auto-downsizes with warning)
- **Gateway allocation**: First usable address in each allocated subnet

#### 5. Temporal Workflow Integration (`app/workflows/`) — Issue #8

Production-grade workflow orchestration replacing the sequential in-process pipeline.

- **Workflow**: `MigrationWorkflow` with 6 activities — discover, normalize, validate, analyze, translate, migrate_data
- **Retry policy**: 3 attempts per activity, exponential backoff (1s initial, 2x coefficient, 30s max interval)
- **Activity timeouts**: 5 min for discovery/normalization/validation/analysis, 10 min for translation, 30 min for data migration
- **Workflow queries**: `current_step()` and `steps_completed()` for real-time progress tracking
- **Validation gate**: Workflow halts with `validation_failed` status if errors detected (unless `skip_validation=true`)
- **Worker**: `app/workflows/worker.py` connects to Temporal server, registers all activities on `migration-task-queue`
- **Infrastructure**: `docker-compose.temporal.yml` with Temporal server (SQLite backend) + Web UI at `localhost:8233`

#### 6. Updated Pipeline & API

- **Orchestrator pipeline expanded**: 5 steps → 7 steps (discover → normalize → **validate** → **analyze** → translate → generate_terraform → migrate_data)
- **New job states**: `VALIDATING`, `ANALYZING`, `VALIDATION_FAILED`
- **New API endpoints**:
  - `POST /validate/{adapter}` — returns validation findings with severity, check name, affected resource
  - `POST /analyze/{adapter}` — returns strategy assignments (per-resource with rationale) + network allocation plan
  - `GET /graph/{adapter}?format=dot` — returns dependency graph as JSON (nodes + edges) + optional Graphviz DOT string + execution order + parallel stages
- **Updated endpoints**:
  - `POST /execute/{adapter}?skip_validation=true` — override validation blocking
  - `GET /status/{job_id}` — now includes `validation_errors`, `validation_warnings`, `strategy_summary`
- **Translation service**: Accepts optional `StrategyResult` and `NetworkPlan`. Backward compatible — Phase 1 calls without these parameters still work identically.
- **VPC model**: `VPCInstance.migration_strategy` field tracks which strategy produced each instance

#### Validated
- 34/34 API endpoint tests passed (both adapters, all Phase 1 + Phase 2 endpoints)
- 8/8 offline tests passed (full pipeline, graph DOT, backward compat, cycle detection, validation blocking, error detection, network conflicts, Temporal imports)
- Full Phase 2 pipeline: discover → normalize → validate → analyze → translate → generate_terraform → migrate_data

#### References
- GitHub Issues: #8, #9, #10, #11, #28

---

## [0.3.0] - 2026-04-06 19:45 IST

### Phase 1 Complete — MVP End-to-End Migration

Phase 1 delivers a fully working migration pipeline from discovery through Terraform generation, validated end-to-end for both IBM Classic and VMware adapters.

#### Added
- **VMware adapter**: Mock vSphere adapter with 3 VMs, 2 vSwitches, full normalization including cross-resource UUID dependencies
- **VPC target models**: Pydantic models for `VPCNetwork`, `VPCSubnet`, `VPCSecurityGroup`, `VPCInstance`, `VPCTranslationResult`
- **Translation engine**: `TranslationService` converts canonical model to IBM VPC — OS image mapping, instance profile selection, CIDR-preserving subnet mapping, security group rule translation
- **Terraform generator**: Jinja2-based `TerraformGenerator` produces valid `main.tf` with VPC, subnets, security groups, instances, volumes, and outputs
- **Sequential orchestrator**: `MigrationOrchestrator` runs async jobs through discover → normalize → translate → terraform → mock data migration pipeline
- **Mock data migration**: Writes per-VM rsync logs, disk inventories, and migration manifests to `output/migrations/{job_id}/`
- **API endpoints**: `POST /plan/{adapter}`, `POST /execute/{adapter}` (async), `GET /status/{job_id}`, `GET /jobs`
- **CLI tool**: Typer-based `migrate` CLI with `adapters`, `discover`, `plan`, `execute`, `status`, `jobs` commands — hits running API via HTTP
- **Response models**: `TranslationResponse`, `JobResponse` with full Pydantic validation

#### Changed (Data Model Alignment — Issue #31)
- **Canonical models**: Added `region`, `image`, `disks` (UUID list), `network_interfaces` (UUID list), `security_groups` (UUID list), `stateful` to `ComputeResource`; added `zone`, `connected_resources` (UUID list) to `NetworkSegment`; added `mount_point` to `StorageVolume`; changed `tags` from `list[str]` to `dict[str, str]` on `BaseResource`
- **SecurityPolicy refactor**: Converted from flat one-object-per-rule to grouped model with `SecurityRule` sub-model (`rules: list[SecurityRule]`, `applied_to: list[UUID]`, `SecurityPolicyType` enum)
- **StorageVolume.attached_to**: Changed from `str` (platform-specific ID) to `UUID | None` (canonical compute resource reference)
- **IBM Classic adapter**: Full rewrite of normalization — populates all new fields, UUID-based cross-references for disks/networks/security groups, grouped SecurityPolicy with SecurityRule list
- **VMware adapter**: Updated normalization — dict tags via `_parse_tags()`, region/image/disks/network_interfaces/stateful/zone/connected_resources/mount_point populated, UUID-based attached_to on storage
- **TranslationService**: Updated `_translate_security_policies()` to consume grouped SecurityPolicy model — each policy becomes a VPC security group with its rules
- **data_model.md**: Updated spec to match implementation — all field names, types, enums, and examples aligned with code
- `pyproject.toml`: Added Jinja2, Typer, httpx as dependencies; added `migrate` CLI entry point
- `dependencies.py`: Extended with `TranslationService` and `MigrationOrchestrator` DI providers
- `main.py`: Wires all Phase 1 services at startup; registers VMware adapter

#### Validated
- 44/44 API endpoint tests passed (both adapters)
- 6/6 offline validation tests passed (models, adapters, translation, Terraform, serialization)
- Full pipeline: discover → normalize → translate → generate_terraform → migrate_data

#### References
- GitHub Issues: #2, #3, #4, #5, #6, #7, #25, #31

---

## [0.1.0] - 2026-04-05 22:54 IST

### Phase 0 — Foundation

#### Added
- **Project structure**: Full `/app` skeleton with `/api`, `/core`, `/adapters`, `/models`, `/services`, `/workflows`, `/terraform`, `/graph`, `/utils` packages
- **Canonical data model**: `ComputeResource`, `NetworkSegment`, `SecurityPolicy`, `StorageVolume`, `KubernetesResource` with UUID IDs, timestamps, and structured `ResourceDependency`
- **Adapter framework**: `AbstractBaseAdapter` ABC with `discover()` (async), `normalize()`, `translate()`, `migrate()` interface
- **Plugin registry**: Config-driven `AdapterRegistry` with auto-discovery of adapter sub-packages
- **IBM Classic adapter**: Mock adapter with realistic SoftLayer data (3 VSIs, 2 VLANs, 2 firewall rules, 3 storage volumes) and full normalization including cross-resource dependencies
- **FastAPI API layer**: `POST /discover/{adapter}` returns raw + normalized data; `GET /adapters` lists registered adapters
- **Dependency injection**: FastAPI `Depends()` pattern via `app/api/dependencies.py`
- **Pydantic response models**: `DiscoveryResponse`, `DiscoveredResources`, `ErrorResponse`, `AdapterListResponse`
- **Structured logging**: JSON-formatted structured logging via `structlog` with context fields
- **Configuration**: `pydantic-settings` with `.env` support and cached `get_settings()`
- **Custom exceptions**: `AdapterNotFoundError`, `AdapterDiscoveryError`, `AdapterRegistrationError`
- **Project tooling**: `pyproject.toml` with FastAPI, Pydantic, structlog, uvicorn; dev deps (pytest, ruff, httpx)

#### References
- GitHub Issues: #1 (Core Architecture Setup), #27 (Plugin Registry & Adapter Factory)
