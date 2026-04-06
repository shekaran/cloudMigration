# Changelog

All notable changes to this project will be documented in this file.

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
