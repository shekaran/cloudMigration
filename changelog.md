# Changelog

All notable changes to this project will be documented in this file.

---

## [0.4.0] - 2026-04-06 23:15 IST

### Phase 2 — Orchestration & Intelligence

Phase 2 adds dependency graph analysis, strategy-aware translation, pre-migration validation, intelligent network planning, and Temporal workflow integration.

#### Added
- **Dependency Graph Engine** (`app/graph/engine.py`): Directed graph from `ResourceDependency` objects, topological sort (Kahn's algorithm), cycle detection (DFS), parallel execution stages, JSON export, Graphviz DOT visualization with color-coded node types and edge styles. Issue #9.
- **Strategy Engine** (`app/services/strategy.py`): Classifies workloads into `lift_and_shift`, `replatform`, `rebuild`, `kubernetes_migration` based on statefulness, resource sizing, OS complexity, dependency count. Strategy changes translation output — replatform VMs get memory-optimized profiles (`mx2` family) and larger boot volumes. Issue #10.
- **Validation Engine** (`app/services/validation.py`): Pre-migration checks with ERROR/WARNING/INFO severity levels. Checks: OS compatibility, CPU/memory limits, NIC count, CIDR format, CIDR overlap, security rule limits, storage limits, orphaned volumes, cyclic dependencies, dangling UUID references. Default blocks execution; overridable with `skip_validation=true`. Issue #11.
- **Network Planner v1** (`app/services/network_planner.py`): Allocates fresh CIDRs from configurable target VPC range (default `10.240.0.0/16`), preserves subnet sizing (prefix length), round-robin zone distribution, conflict detection (overlap, exhaustion, sizing). Issue #28.
- **Temporal Workflow Integration**: `MigrationWorkflow` with 6 activities (discover, normalize, validate, analyze, translate, migrate_data), retry policy (3 attempts, exponential backoff), workflow queries for current step and progress, Temporal worker with task queue. `docker-compose.temporal.yml` for server setup. Issue #8.
- **New API endpoints**: `POST /validate/{adapter}`, `POST /analyze/{adapter}` (strategy + network plan), `GET /graph/{adapter}?format=dot` (dependency graph with Graphviz DOT)
- **Execution pipeline**: 7-step pipeline — discover → normalize → validate → analyze → translate → generate_terraform → migrate_data
- `VPCInstance.migration_strategy` field for strategy-aware Terraform output
- `JobResponse` extended with `validation_errors`, `validation_warnings`, `strategy_summary`
- `POST /execute/{adapter}?skip_validation=true` to override validation blocking

#### Changed
- **TranslationService**: Accepts optional `StrategyResult` and `NetworkPlan`. Replatform VMs get `mx2-*` profiles and 200GB+ boot volumes. Network plan CIDRs replace source CIDRs. Backward compatible — Phase 1 calls still work.
- **MigrationOrchestrator**: Integrates all Phase 2 engines. Pipeline expanded from 5 to 7 steps. New `VALIDATING`, `ANALYZING`, `VALIDATION_FAILED` job states.
- **dependencies.py**: Extended with `StrategyEngine`, `ValidationEngine`, `NetworkPlanner` DI providers
- **main.py**: Wires all Phase 2 engines at startup; registers analysis router
- **pyproject.toml**: Added `temporalio>=1.24.0`; version bumped to 0.4.0

#### Validated
- 34/34 API endpoint tests passed (both adapters, all Phase 2 endpoints)
- 8/8 offline validation tests passed (graph, strategy, validation, network, cycle detection, error detection, conflict detection, Temporal imports)
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
