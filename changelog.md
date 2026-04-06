# Changelog

All notable changes to this project will be documented in this file.

---

## [0.2.1] - 2026-04-06 07:00 IST

### Data Model Alignment (Issue #31)

#### Changed
- **Canonical models**: Added `region`, `image`, `disks` (UUID list), `network_interfaces` (UUID list), `security_groups` (UUID list), `stateful` to `ComputeResource`; added `zone`, `connected_resources` (UUID list) to `NetworkSegment`; added `mount_point` to `StorageVolume`; changed `tags` from `list[str]` to `dict[str, str]` on `BaseResource`
- **SecurityPolicy refactor**: Converted from flat one-object-per-rule to grouped model with `SecurityRule` sub-model (`rules: list[SecurityRule]`, `applied_to: list[UUID]`, `SecurityPolicyType` enum)
- **IBM Classic adapter**: Full rewrite of normalization — populates all new fields, UUID-based cross-references for disks/networks/security groups, grouped SecurityPolicy with SecurityRule list
- **VMware adapter**: Updated normalization — dict tags via `_parse_tags()`, region/image/disks/network_interfaces/stateful/zone/connected_resources/mount_point populated
- **TranslationService**: Updated `_translate_security_policies()` to consume grouped SecurityPolicy model (iterates `policy.rules` instead of flat policy fields)

#### References
- GitHub Issue: #31

---

## [0.2.0] - 2026-04-06 06:23 IST

### Phase 1 — MVP (End-to-End Migration)

#### Added
- **VMware adapter**: Mock vSphere adapter with 3 VMs, 2 vSwitches, full normalization including cross-resource dependencies
- **VPC target models**: Pydantic models for `VPCNetwork`, `VPCSubnet`, `VPCSecurityGroup`, `VPCInstance`, `VPCTranslationResult`
- **Translation engine**: `TranslationService` converts canonical model to IBM VPC — OS image mapping, instance profile selection, CIDR-preserving subnet mapping, security group rule translation
- **Terraform generator**: Jinja2-based `TerraformGenerator` produces valid `main.tf` with VPC, subnets, security groups, instances, volumes, and outputs
- **Sequential orchestrator**: `MigrationOrchestrator` runs async jobs through discover → normalize → translate → terraform → mock data migration pipeline
- **Mock data migration**: Writes per-VM rsync logs, disk inventories, and migration manifests to `output/migrations/{job_id}/`
- **New API endpoints**: `POST /plan/{adapter}`, `POST /execute/{adapter}` (async), `GET /status/{job_id}`, `GET /jobs`
- **CLI tool**: Typer-based `migrate` CLI with `adapters`, `discover`, `plan`, `execute`, `status`, `jobs` commands — hits running API via HTTP
- **New response models**: `TranslationResponse`, `JobResponse` with full Pydantic validation

#### Changed
- `pyproject.toml`: Added Jinja2, Typer, httpx as dependencies; added `migrate` CLI entry point
- `dependencies.py`: Extended with `TranslationService` and `MigrationOrchestrator` DI providers
- `main.py`: Wires all Phase 1 services at startup; registers VMware adapter

#### References
- GitHub Issues: #2, #3, #4, #5, #6, #7, #25

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
