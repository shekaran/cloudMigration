# GitHub Issues — Multi-Platform Migration Orchestration Engine

> Repository: [shekaran/cloudMigration](https://github.com/shekaran/cloudMigration)
>
> This document maps every GitHub issue to its source references in the project documentation.

---

## Phase 0 — Foundation

| # | Issue | Source References |
|---|-------|-------------------|
| [#1](https://github.com/shekaran/cloudMigration/issues/1) | Core Architecture Setup | `project_spec.md` §3.2, §5, §17 · `architecture.md` §3, §5, §6 · `claude.md` §3, §4.2 · `execution_plan.md` §3 |
| [#27](https://github.com/shekaran/cloudMigration/issues/27) | Plugin Registry & Adapter Factory | `architecture.md` §3.2 (Plugin System), §6 (Factory Pattern), §8 (Extensibility Model) · `claude.md` §3.4 |

---

## Phase 1 — MVP

| # | Issue | Source References |
|---|-------|-------------------|
| [#2](https://github.com/shekaran/cloudMigration/issues/2) | IBM Classic Adapter | `project_spec.md` §2.1, §5.2 · `architecture.md` §3.2 · `claude.md` §6 · `execution_plan.md` §4 |
| [#3](https://github.com/shekaran/cloudMigration/issues/3) | VMware Adapter (VM only) | `project_spec.md` §2.1, §5.2 · `architecture.md` §3.2 · `claude.md` §6 · `execution_plan.md` §4 |
| [#4](https://github.com/shekaran/cloudMigration/issues/4) | Translation Engine (VM → VPC VSI, VLAN → Subnet) | `project_spec.md` §8 · `architecture.md` §3.5 · `execution_plan.md` §4 |
| [#5](https://github.com/shekaran/cloudMigration/issues/5) | Terraform Generator (VPC, Subnet, Compute) | `project_spec.md` §9 · `architecture.md` §3.6 · `claude.md` §8 · `execution_plan.md` §4 |
| [#6](https://github.com/shekaran/cloudMigration/issues/6) | Sequential Migration Orchestrator (No Temporal) | `project_spec.md` §18 (MVP: sequential, no Temporal) · `execution_plan.md` §4 |
| [#7](https://github.com/shekaran/cloudMigration/issues/7) | API Layer (FastAPI endpoints) | `project_spec.md` §15 · `architecture.md` §3.1 · `claude.md` §10 · `execution_plan.md` §4 |
| [#25](https://github.com/shekaran/cloudMigration/issues/25) | CLI Tool (Typer) | `project_spec.md` §4 (Technology Stack: Typer) · `execution_plan.md` §4 (CLI or API-triggered) |

---

## Phase 2 — Orchestration & Intelligence

| # | Issue | Source References |
|---|-------|-------------------|
| [#8](https://github.com/shekaran/cloudMigration/issues/8) | Temporal Workflow Integration | `project_spec.md` §11 · `architecture.md` §3.8 · `claude.md` §7 · `execution_plan.md` §5 |
| [#9](https://github.com/shekaran/cloudMigration/issues/9) | Dependency Graph Engine | `project_spec.md` §7 · `architecture.md` §3.4 · `claude.md` §9 · `execution_plan.md` §5 |
| [#10](https://github.com/shekaran/cloudMigration/issues/10) | Strategy Engine | `project_spec.md` §10 · `architecture.md` §3.7 · `execution_plan.md` §5 |
| [#11](https://github.com/shekaran/cloudMigration/issues/11) | Validation Engine (Pre-migration Checks) | `execution_plan.md` §5 · `architecture.md` §3.5 (conflict detection) |
| [#28](https://github.com/shekaran/cloudMigration/issues/28) | Network Planner v1 (CIDR Allocation & Conflict Detection) | `execution_plan.md` §5 (Phase 2: Network Planner v1) · `project_spec.md` §8.3 · `architecture.md` §3.5 |

---

## Phase 3 — Network & Security Expansion

| # | Issue | Source References |
|---|-------|-------------------|
| [#12](https://github.com/shekaran/cloudMigration/issues/12) | VMware NSX Support | `project_spec.md` §2.1 · `execution_plan.md` §6 · `architecture.md` §3.5 |
| [#13](https://github.com/shekaran/cloudMigration/issues/13) | Firewall Translation Engine | `project_spec.md` §14 · `architecture.md` §3.9 · `execution_plan.md` §6 |
| [#14](https://github.com/shekaran/cloudMigration/issues/14) | Advanced Network Planning | `execution_plan.md` §6 · `project_spec.md` §8.3 · `architecture.md` §3.5 |

---

## Phase 4 — Kubernetes & Modernization

| # | Issue | Source References |
|---|-------|-------------------|
| [#15](https://github.com/shekaran/cloudMigration/issues/15) | Kubernetes Migration (Backup/Restore/Validate) | `project_spec.md` §13 · `architecture.md` §3.9 · `execution_plan.md` §7 |

---

## Phase 5 — Advanced Platforms

| # | Issue | Source References |
|---|-------|-------------------|
| [#16](https://github.com/shekaran/cloudMigration/issues/16) | Bare Metal Adapter | `project_spec.md` §2.1, §5.2 · `execution_plan.md` §8 |
| [#17](https://github.com/shekaran/cloudMigration/issues/17) | Hyper-V Adapter | `project_spec.md` §2.1, §5.2 · `execution_plan.md` §8 |
| [#18](https://github.com/shekaran/cloudMigration/issues/18) | Incremental Data Migration & DB Replication | `project_spec.md` §12 · `execution_plan.md` §8 |

---

## Phase 6 — Productization

| # | Issue | Source References |
|---|-------|-------------------|
| [#19](https://github.com/shekaran/cloudMigration/issues/19) | Dry Run / Simulation Mode | `project_spec.md` §19 · `execution_plan.md` §9 |
| [#20](https://github.com/shekaran/cloudMigration/issues/20) | Reporting & Risk Analysis Engine | `execution_plan.md` §9 |
| [#29](https://github.com/shekaran/cloudMigration/issues/29) | UI Dashboard | `project_spec.md` §19 · `execution_plan.md` §9 |
| [#30](https://github.com/shekaran/cloudMigration/issues/30) | Multi-Cloud Extension (AWS/Azure) | `project_spec.md` §19 · `execution_plan.md` §9 · `architecture.md` §13 |

---

## Cross-cutting Concerns

| # | Issue | Source References |
|---|-------|-------------------|
| [#21](https://github.com/shekaran/cloudMigration/issues/21) | Observability — Structured Logging & Workflow Tracking | `architecture.md` §10 · `claude.md` §4.3 · `project_spec.md` §16.4 |
| [#22](https://github.com/shekaran/cloudMigration/issues/22) | Security Hardening — Config-driven Secrets & Log Masking | `architecture.md` §11 · `claude.md` §2.5 · `project_spec.md` §16.5 |
| [#23](https://github.com/shekaran/cloudMigration/issues/23) | Testing Framework & Sample Test Data | `claude.md` §11 · `project_spec.md` §22 |
| [#24](https://github.com/shekaran/cloudMigration/issues/24) | Documentation Maintenance | `claude.md` §2.0 · `project_spec.md` §20 |
| [#26](https://github.com/shekaran/cloudMigration/issues/26) | Docker & Containerization | `project_spec.md` §4 (Technology Stack: Docker) |

---

## Source Document Index

| Document | Description |
|----------|-------------|
| `project_spec.md` | Full project specification — scope, models, tech stack, APIs, NFRs |
| `execution_plan.md` | Phased execution plan — phase objectives, deliverables, success criteria |
| `architecture.md` | System architecture — components, data flow, patterns, constraints |
| `claude.md` | Implementation guidelines — code quality, design rules, testing expectations |
