# Claude Instructions: Multi-Platform Migration Orchestration Engine

---

# 1. Purpose of This File

This file defines how Claude should behave when generating code for this project.

The goal is to ensure:

* Production-quality architecture
* Consistency across modules
* Extensibility for future platforms
* Avoidance of simplistic or tightly coupled implementations

---

# 2. Core Principles (MANDATORY)

## 2.0 Documentation
* Update files in the docs folder after major milestones and major additions to the project

## 2.1 Treat This as a Platform, Not a Script

* DO NOT generate one-off scripts
* DO NOT hardcode logic
* ALWAYS design for extensibility

---

## 2.2 Follow Clean Architecture

* Separate concerns clearly:

  * API layer
  * Business logic
  * Adapters
  * Models
  * Infrastructure

* No cross-layer leakage

---

## 2.3 Use Abstractions and Interfaces

* All adapters must inherit from a base interface
* Avoid direct dependency between adapters
* Use dependency injection where possible

---

## 2.4 Idempotency is Required

* All operations must be repeatable
* Avoid side effects without checks
* Design for retries

---

## 2.5 Configuration Driven

* No hardcoded values
* Use config files or environment variables

---

# 3. Architecture Guidelines

## 3.1 Adapter-Based Design

* Each platform (IBM, VMware, Hyper-V, etc.) must be implemented as a separate adapter
* Adapters must not depend on each other
* Adapters must output canonical data

---

## 3.2 Canonical Model First

* All data must be normalized before processing
* Translation must ONLY work on canonical model

---

## 3.3 Loose Coupling

* Services must communicate via defined interfaces
* Avoid tight binding between modules

---

## 3.4 Plugin-Friendly Design

* Adapters should be pluggable
* System should support adding new adapters without modifying core logic

---

# 4. Code Quality Requirements

## 4.1 Language Standards

* Use Python 3.10+
* Use type hints everywhere
* Follow PEP8

---

## 4.2 Structure

Follow this structure strictly:

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

## 4.3 Logging

* Use structured logging
* Include context (job_id, resource_id)

---

## 4.4 Error Handling

* Fail fast on invalid input
* Provide meaningful error messages
* Avoid silent failures

---

# 5. Implementation Rules

## 5.1 DO NOT

* Do NOT simplify architecture
* Do NOT merge layers
* Do NOT hardcode infrastructure logic
* Do NOT skip dependency graph
* Do NOT tightly couple Terraform with business logic

---

## 5.2 ALWAYS

* Write modular code
* Use interfaces/abstract base classes
* Provide docstrings
* Include realistic mock data
* Ensure components are independently testable

---

# 6. Adapter Requirements

Each adapter must:

1. Simulate API interaction (mock data)

2. Implement:

   * discover()
   * normalize()
   * translate()
   * migrate()

3. Output canonical model

---

# 7. Workflow Requirements

* Use Temporal for orchestration

* Workflows must:

  * Support retries
  * Handle failures
  * Maintain state

* Avoid simple sequential scripts

---

# 8. Terraform Requirements

* Generate Terraform code using templates
* Keep Terraform generation separate from execution logic
* Use modular templates

---

# 9. Dependency Graph Requirements

* Must be implemented

* Must support:

  * Topological sorting
  * Cycle detection

* Must be used in execution planning

---

# 10. API Requirements

* Use FastAPI
* Keep endpoints thin (no business logic inside controllers)
* Delegate logic to services

---

# 11. Testing Expectations

* Code must be testable
* Provide sample test data
* Avoid untestable monolithic functions

---

# 12. Iterative Development Approach

When generating code:

1. Start with structure and models
2. Then implement adapters
3. Then graph engine
4. Then translation
5. Then Terraform
6. Then workflows
7. Then API layer

DO NOT generate everything at once.

---

# 13. Output Expectations

When responding:

* Provide complete code (not partial snippets)
* Maintain consistency with project structure
* Ensure imports and dependencies are correct
* Avoid placeholder logic unless explicitly requested

---

# 14. Common Pitfalls to Avoid

* Oversimplifying orchestration
* Ignoring network complexity
* Skipping firewall translation
* Hardcoding resource mappings
* Mixing infrastructure and business logic

---

# 15. Design Mindset

Think like:

* Platform engineer
* Cloud architect
* Distributed systems designer

NOT like:

* Script writer
* Demo builder

---

# 16. Final Instruction

If unsure between simplicity and extensibility:

👉 ALWAYS choose extensibility and correctness over simplicity.

---
