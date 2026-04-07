# Changelog

All notable changes to this project will be documented in this file.

---

## [0.8.0] - 2026-04-08 06:15 IST

### Phase 5.1 — Replication, Reliability & Usability

Phase 5.1 adds formal replication/checkpoint data models, checksum-based data integrity verification, a reliability layer with retry policies and idempotent execution, a continuous delta sync (CDC) replication engine with parallel sync and cutover optimization, dry-run simulation mode, a CLI quickstart wizard with blueprint templates, and a full blueprint engine for guided migration workflows.

#### 1. ReplicationState & ExecutionCheckpoint Models (`app/models/replication.py`) — Issue #31

First-class Pydantic entities for tracking replication lifecycle and execution recovery.

- **ReplicationState**: Per-resource tracking — status lifecycle (pending → syncing → delta_syncing → quiesced → validating → completed), data transfer progress, checksum records, retry counts
- **ExecutionCheckpoint**: Workflow-level checkpoint — captures stage, resource IDs, replication state snapshots, metadata (WAL positions, plan IDs)
- **ChecksumRecord**: Per-volume/database checksum with algorithm, source/target hashes, verification status
- **Status enums**: ReplicationStatus (10 states), CheckpointStatus (4 states), ChecksumAlgorithm (SHA256, MD5, XXH3)

#### 2. Checksum Validation & Data Integrity (`app/services/data_migration.py`) — Issue #32

SHA-256 integrity verification integrated into the data migration validate phase.

- **Per-volume checksums**: Source and target checksums computed for every synced volume
- **Per-database checksums**: Database-level integrity verification post-replication
- **Verification reporting**: ChecksumRecord list on DataMigrationPlan, per-resource verification on ReplicationState
- **Failure detection**: Validation flags failed checksums with specific target names

#### 3. Checkpoint Resume & Recovery — Issue #33

Persist migration plans and resume from last checkpoint after failure.

- **Plan persistence**: Plans written to disk as JSON after each checkpoint-creating phase
- **Plan loading**: `load_plan(job_id)` deserializes a persisted plan
- **Resume**: `resume(plan)` determines completed stages and continues from next stage
- **Checkpoint lifecycle**: Active → Superseded (when newer checkpoint created) → Used for Resume
- **API endpoint**: `POST /resume/{job_id}` for resuming failed jobs
- **CLI command**: `migrate resume <job_id>` with poll support

#### 4. Reliability Layer (`app/services/reliability.py`) — Issue #34

Configurable retry policies, idempotent execution, and compensation/rollback.

- **RetryPolicy**: Max retries, exponential/linear/fixed backoff, configurable retryable error types
- **IdempotencyTracker**: Deterministic operation keys, cached results, skip-on-complete
- **ReliabilityManager**: Wraps operations with retry + idempotency + compensation registration
- **CompensationAction**: LIFO rollback of registered compensations
- **Integration**: Wired into MigrationOrchestrator constructor

#### 5. Continuous Delta Sync & Parallel Sync (`app/services/replication_engine.py`) — Issue #35

CDC-like replication engine with parallel volume sync and cutover optimization.

- **Continuous sync**: Iterative delta sync until convergence (delta < threshold MB), configurable intervals, max iterations, lag tracking
- **Parallel sync**: Concurrent volume synchronization with semaphore-based concurrency control, priority scheduling (CRITICAL > HIGH > NORMAL > LOW)
- **Cutover optimization**: Downtime estimation, pre-staging tracking, parallel cutover groups (boot disks + data volumes), readiness check against max downtime target
- **Models**: ContinuousSyncConfig, ParallelSyncConfig, CutoverConfig, SyncIteration, VolumeSyncTask, CutoverPlan

#### 6. Dry Run / Simulation Mode — Issue #19 (moved from Phase 6)

Simulate migrations without data transfer for validation and planning.

- **`--dry-run` flag**: On API `POST /execute/{adapter}?dry_run=true` and CLI `migrate execute --dry-run`
- **Dry-run report**: JSON report with what-would-happen steps, data estimates, resource mappings
- **Plan generation**: Builds full data migration plan without executing transfer phases
- **Cutover estimation**: If replication engine available, estimates downtime even in dry-run
- **Job tracking**: `dry_run` field on MigrationJob and JobResponse

#### 7. CLI Quickstart & Prebuilt Templates — Issue #36

Interactive wizard and template-based migration execution.

- **`migrate quickstart`**: Interactive guided setup — template selection, prerequisite check, configuration, execution
- **`migrate templates`**: List all available blueprint templates with category, platform, risk level
- **`migrate template-info <name>`**: Detailed template view — prerequisites, steps, parameters
- **`migrate template-run <name>`**: Execute a migration from a template with `--dry-run` and `--skip-validation`
- **`migrate resume <job_id>`**: Resume a failed migration from last checkpoint

#### 8. Blueprint Engine (`app/blueprints/`) — Issue #37

Prebuilt migration templates and guided workflow engine.

- **5 templates**: lift-and-shift-vmware, replatform-ibm-classic, k8s-migration, bare-metal-rebuild, hyperv-lift-and-shift
- **YAML-based**: Templates defined in `app/blueprints/templates/*.yaml` with parameters, steps, prerequisites
- **BlueprintEngine**: Template registry with auto-discovery, category/platform filtering, parameter validation
- **BlueprintInstance**: Configured instance with resolved template variables, step-by-step progression
- **Template variables**: `{{ param }}` syntax resolved at configure time from defaults + user overrides

#### Files Changed

| File | Change |
|------|--------|
| `app/models/replication.py` | **NEW** — ReplicationState, ExecutionCheckpoint, ChecksumRecord models |
| `app/services/reliability.py` | **NEW** — RetryPolicy, IdempotencyTracker, ReliabilityManager |
| `app/services/replication_engine.py` | **NEW** — Continuous sync, parallel sync, cutover optimization |
| `app/blueprints/__init__.py` | **NEW** — Blueprint package |
| `app/blueprints/engine.py` | **NEW** — BlueprintEngine, template loading and workflow |
| `app/blueprints/templates/*.yaml` | **NEW** — 5 blueprint templates |
| `app/services/data_migration.py` | **UPDATED** — Checksum validation, replication states, checkpoint persistence, resume |
| `app/services/orchestrator.py` | **UPDATED** — Dry-run mode, replication engine integration, new job fields |
| `app/models/responses.py` | **UPDATED** — 8 new fields on JobResponse |
| `app/api/routes/migration.py` | **UPDATED** — dry_run param, resume endpoint, new response fields |
| `app/cli.py` | **UPDATED** — quickstart, templates, template-run, resume, dry-run support |
| `app/main.py` | **UPDATED** — Wire ReplicationEngine, ReliabilityManager, BlueprintEngine; version 0.8.0 |
| `pyproject.toml` | **UPDATED** — Version 0.8.0, PyYAML dependency |
| `docs/issues.md` | **UPDATED** — Phase 5.1 section with issues #31-#37, #19 moved from Phase 6 |

---

## [0.7.0] - 2026-04-07 17:00 IST

### Phase 5 — Advanced Platforms

Phase 5 adds Bare Metal and Hyper-V adapters for full heterogeneous platform support, plus an advanced data migration service with incremental sync, database replication, and pre/post migration hooks with rollback capability.

#### 1. Bare Metal Adapter (`app/adapters/bare_metal/`) — Issue #20

Complex bare metal server fleet with RAID, GPU, bonded NICs, and BMC/IPMI metadata.

- **Mock data**: 5 servers — Dell R740xd (DB, dual-NIC bond, RAID1+RAID0, 256GB), Dell R750 (App, RAID5, 512GB), Dell R750xa (GPU, 4x A100 80GB), IBM Power S922 (AIX 7.3, POWER9, legacy ERP), HPE DL380 (Web, single disk, Legacy BIOS)
- **RAID normalization**: Boot RAID array → `storage_gb` on ComputeResource, data RAID arrays → `StorageVolume` with IOPS hints (NVMe=100K, SSD=50K)
- **NIC bonding**: Bond metadata captured (802.3ad/active-backup modes, slave interfaces, speed)
- **GPU support**: GPU model, count, memory, CUDA version captured in compute metadata
- **BMC/IPMI**: BMC type (iDRAC9, HMC, iLO5), IP, firmware version in metadata
- **BIOS types**: UEFI, Legacy, OPAL (IBM Power) tracked for migration compatibility
- **Architecture**: x86_64 and ppc64le (POWER9) support
- **Strategy routing**: Bare metal → `rebuild` strategy (7 resources), supported OS → `lift_and_shift` (4 resources)
- **Total resources**: 11 (5 servers + 3 networks + 2 RAID volumes + 1 security policy)

#### 2. Hyper-V Adapter (`app/adapters/hyperv/`) — Issue #21

Full Hyper-V environment with SCVMM integration, checkpoints, and replication.

- **Mock data**: 5 VMs — DC-PROD-01 (AD Domain Controller, Gen2, replicated), SQL-PROD-01 (SQL Server 2019, 64GB static, 4 disks, 2 checkpoints), WEB-PROD-01 (IIS, dynamic memory), APP-PROD-01 (legacy .NET, Gen1, VHD format), FILE-PROD-01 (file server, 2TB share, replicated)
- **VHD/VHDX formats**: Both VHD (legacy) and VHDX tracked with disk type (Fixed/Dynamic), current vs max size
- **Hyper-V Replica**: Replication mode (Primary), state, frequency, replica server in metadata
- **Checkpoints**: Production and Standard checkpoints with creation time and size
- **SCVMM integration**: Cloud assignment, service templates, custom properties (CostCenter, Owner)
- **Dynamic memory**: Min/max/buffer tracked; memory_gb derived from startup_mb
- **Cluster awareness**: Failover cluster name, node, high availability flag
- **Generation**: Gen1 (IDE boot) vs Gen2 (SCSI boot, Secure Boot) tracked
- **Total resources**: 15 (5 VMs + 3 virtual switches + 6 VHD/VHDX volumes + 1 security policy)

#### 3. Advanced Data Migration Service (`app/services/data_migration.py`) — Issue #22

Full-lifecycle data migration with incremental sync, database replication, and rollback.

- **Incremental sync**: Dirty block tracking per volume, delta transfer estimation, configurable block size (4MB default)
- **Bandwidth estimation**: Calculates full sync and delta sync time based on available bandwidth (configurable) and compression ratio (default 0.6)
- **Database replication**: Auto-detects databases from compute metadata (PostgreSQL, MySQL, MSSQL, Oracle), configures replication method:
  - PostgreSQL → WAL shipping with `pg_switch_wal()` quiesce hook
  - MySQL → Logical replication with `FLUSH TABLES WITH READ LOCK` quiesce hook
  - MSSQL → Dump/restore with `BACKUP DATABASE` quiesce hook
- **Migration lifecycle**: 8 phases — idle → pre_sync → initial_sync → incremental_sync → quiesce → final_sync → cutover → validate → completed
- **Pre/post hooks**: Standard hooks for connectivity verification, snapshot creation, quiesce (filesystem sync, DB checkpoint), DNS cutover, load balancer update, data integrity validation
- **Rollback checkpoints**: Created after incremental sync and quiesce; `rollback()` reverts to latest checkpoint with DNS/LB revert hooks
- **Plan persistence**: Full migration plan written to disk as JSON
- **Sync mode detection**: Automatically selects `database` mode when DB detected, otherwise `incremental`

#### 4. Updated Pipeline & API

- **Orchestrator**: Advanced data migration replaces mock rsync when `AdvancedDataMigrationService` is provided
- **New `MigrationJob` fields**: `data_migration_plan_id`, `data_sync_mode`, `data_total_gb`, `data_delta_gb`, `db_replications`, `migration_hooks_executed`, `rollback_checkpoints`
- **New adapters in registry**: `bare_metal` and `hyperv` added to `ADAPTER_CONFIG`
- **`JobResponse` extended**: 7 new fields for data migration reporting
- **Backward compatible**: All existing adapters and endpoints work unchanged
- **Version**: 0.7.0

#### Validated
- 4/4 adapter tests passed (bare metal discovery/normalization, hyper-v discovery/normalization)
- 7/7 data migration tests passed (plan, full pipeline, DB replication detection, rollback)
- 5/5 orchestrator pipeline tests passed (bare metal, hyper-v, vmware, ibm_classic, kubernetes)
- 32/32 API endpoint tests passed (all 5 adapters, all Phase 1-5 endpoints)
- Bare metal: 11 resources, rebuild strategy for 7, PostgreSQL WAL shipping detected, 13.7TB total data
- Hyper-V: 15 resources, SQL Server MSSQL replication detected, 4.7TB total data
- IBM Classic: incremental sync mode (no DB detected), 3.8TB total data
- VMware/K8s: backward compatible, unchanged behavior

#### References
- GitHub Issues: #20, #21, #22

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
