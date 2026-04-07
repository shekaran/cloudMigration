"""CLI tool for the Migration Orchestration Engine — hits the running API via HTTP.

Commands:
- adapters          List registered adapters
- discover          Run discovery for a source platform
- plan              Generate migration plan and Terraform
- execute           Execute a full migration (with --dry-run support)
- status            Check migration job status
- jobs              List all migration jobs
- quickstart        Interactive guided migration setup
- templates         List available blueprint templates
- template-info     Show details of a specific template
- template-run      Run a migration from a blueprint template
- resume            Resume a failed migration from last checkpoint
"""

import json
import time
from pathlib import Path

import httpx
import typer
import yaml

app = typer.Typer(
    name="migrate",
    help="Migration Orchestration Engine CLI — interact with the running API.",
)

DEFAULT_BASE_URL = "http://localhost:8000"
TEMPLATE_DIR = Path(__file__).parent / "blueprints" / "templates"


def _base_url() -> str:
    return DEFAULT_BASE_URL


def _handle_response(response: httpx.Response) -> dict:
    """Check response status and return JSON, or exit with error."""
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text)
        typer.echo(f"Error ({response.status_code}): {detail}", err=True)
        raise typer.Exit(code=1)
    return response.json()


@app.command()
def adapters() -> None:
    """List all registered adapters."""
    with httpx.Client() as client:
        resp = client.get(f"{_base_url()}/adapters")
    data = _handle_response(resp)
    typer.echo(f"Registered adapters ({data['count']}):")
    for name in data["adapters"]:
        typer.echo(f"  - {name}")


@app.command()
def discover(adapter: str) -> None:
    """Run discovery for a source platform adapter."""
    typer.echo(f"Discovering resources via '{adapter}' adapter...")
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/discover/{adapter}")
    data = _handle_response(resp)

    typer.echo(f"\nAdapter: {data['adapter']}")
    typer.echo(f"Total resources: {data['resource_count']}")
    normalized = data["normalized"]
    typer.echo(f"  Compute:    {len(normalized['compute'])}")
    typer.echo(f"  Networks:   {len(normalized['networks'])}")
    typer.echo(f"  Security:   {len(normalized['security_policies'])}")
    typer.echo(f"  Storage:    {len(normalized['storage'])}")

    typer.echo("\nCompute resources:")
    for vm in normalized["compute"]:
        typer.echo(f"  {vm['name']:20s}  {vm['cpu']}cpu / {vm['memory_gb']}GB  {vm['os']}")


@app.command()
def plan(adapter: str) -> None:
    """Generate a migration plan and Terraform code for a source platform."""
    typer.echo(f"Planning migration for '{adapter}'...")
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{_base_url()}/plan/{adapter}")
    data = _handle_response(resp)

    typer.echo(f"\nMigration Plan:")
    typer.echo(f"  VPC:              {data['vpc_name']}")
    typer.echo(f"  Subnets:          {data['subnets']}")
    typer.echo(f"  Instances:        {data['instances']}")
    typer.echo(f"  Security Groups:  {data['security_groups']}")
    typer.echo(f"  Terraform output: {data['terraform_path']}")


@app.command()
def execute(
    adapter: str,
    poll: bool = typer.Option(True, help="Poll until job completes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate migration without data transfer"),
    skip_validation: bool = typer.Option(False, "--skip-validation", help="Skip validation errors"),
) -> None:
    """Execute a full migration for a source platform (async)."""
    mode = "DRY RUN" if dry_run else "LIVE"
    typer.echo(f"Starting migration for '{adapter}' [{mode}]...")

    params = {}
    if skip_validation:
        params["skip_validation"] = "true"
    if dry_run:
        params["dry_run"] = "true"

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/execute/{adapter}", params=params)
    data = _handle_response(resp)

    job_id = data["job_id"]
    typer.echo(f"Job started: {job_id}")
    if dry_run:
        typer.echo("  Mode: DRY RUN (no data will be transferred)")

    if not poll:
        typer.echo(f"Poll status with: migrate status {job_id}")
        return

    # Poll until done
    typer.echo("Waiting for completion...\n")
    with httpx.Client(timeout=10) as client:
        while True:
            time.sleep(0.5)
            resp = client.get(f"{_base_url()}/status/{job_id}")
            data = _handle_response(resp)
            status = data["status"]
            steps = ", ".join(data.get("steps_completed", []))
            typer.echo(f"  Status: {status:25s}  Steps: [{steps}]")

            if status in ("completed", "failed"):
                break

    typer.echo("")
    if data["status"] == "completed":
        typer.echo(f"Migration completed successfully!")
        typer.echo(f"  Resources migrated: {data['resource_count']}")
        typer.echo(f"  Terraform output:   {data.get('terraform_output', 'N/A')}")
        typer.echo(f"  Migration output:   {data.get('migration_output_dir', 'N/A')}")
        if dry_run:
            typer.echo(f"  Dry run:            Yes (no data transferred)")
        if data.get("checksums_verified", 0) > 0:
            typer.echo(f"  Checksums verified: {data['checksums_verified']}")
            typer.echo(f"  Checksums passed:   {data.get('checksums_passed', 'N/A')}")
        if data.get("continuous_sync_iterations", 0) > 0:
            typer.echo(f"  Sync iterations:    {data['continuous_sync_iterations']}")
            typer.echo(f"  Converged:          {data.get('replication_converged', False)}")
        if data.get("estimated_downtime_seconds", 0) > 0:
            typer.echo(f"  Est. downtime:      {data['estimated_downtime_seconds']:.1f}s")
            typer.echo(f"  Cutover ready:      {data.get('cutover_ready', False)}")
    else:
        typer.echo(f"Migration FAILED: {data.get('error', 'unknown')}", err=True)
        raise typer.Exit(code=1)


@app.command()
def status(job_id: str) -> None:
    """Check the status of a migration job."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{_base_url()}/status/{job_id}")
    data = _handle_response(resp)

    typer.echo(f"Job:       {data['job_id']}")
    typer.echo(f"Adapter:   {data['adapter']}")
    typer.echo(f"Status:    {data['status']}")
    typer.echo(f"Dry run:   {data.get('dry_run', False)}")
    typer.echo(f"Started:   {data['started_at']}")
    if data.get("completed_at"):
        typer.echo(f"Completed: {data['completed_at']}")
    typer.echo(f"Resources: {data['resource_count']}")
    typer.echo(f"Steps:     {', '.join(data.get('steps_completed', []))}")
    if data.get("error"):
        typer.echo(f"Error:     {data['error']}")
    if data.get("terraform_output"):
        typer.echo(f"Terraform: {data['terraform_output']}")
    if data.get("migration_output_dir"):
        typer.echo(f"Migration: {data['migration_output_dir']}")
    # Phase 5.1 fields
    if data.get("checksums_verified", 0) > 0:
        typer.echo(f"Checksums: {data['checksums_verified']} verified, passed={data.get('checksums_passed')}")
    if data.get("continuous_sync_iterations", 0) > 0:
        typer.echo(f"CDC sync:  {data['continuous_sync_iterations']} iterations, converged={data.get('replication_converged')}")
    if data.get("estimated_downtime_seconds", 0) > 0:
        typer.echo(f"Downtime:  {data['estimated_downtime_seconds']:.1f}s estimated, ready={data.get('cutover_ready')}")


@app.command()
def jobs() -> None:
    """List all migration jobs."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{_base_url()}/jobs")
    data = _handle_response(resp)

    if not data:
        typer.echo("No jobs found.")
        return

    typer.echo(f"{'JOB ID':38s}  {'ADAPTER':15s}  {'STATUS':20s}  {'RESOURCES':>9s}  {'DRY RUN':>7s}")
    typer.echo("-" * 100)
    for job in data:
        typer.echo(
            f"{job['job_id']:38s}  {job['adapter']:15s}  "
            f"{job['status']:20s}  {job['resource_count']:>9d}  "
            f"{'Yes' if job.get('dry_run') else 'No':>7s}"
        )


# --- Blueprint / Template Commands ---

@app.command()
def templates() -> None:
    """List available migration blueprint templates."""
    if not TEMPLATE_DIR.exists():
        typer.echo("No templates directory found.", err=True)
        raise typer.Exit(code=1)

    yaml_files = sorted(TEMPLATE_DIR.glob("*.yaml"))
    if not yaml_files:
        typer.echo("No templates found.")
        return

    typer.echo(f"Available migration templates ({len(yaml_files)}):\n")
    typer.echo(f"{'NAME':30s}  {'CATEGORY':16s}  {'PLATFORM':12s}  {'RISK':6s}  DESCRIPTION")
    typer.echo("-" * 110)

    for yaml_file in yaml_files:
        try:
            raw = yaml.safe_load(yaml_file.read_text())
            typer.echo(
                f"{raw['name']:30s}  {raw.get('category', ''):16s}  "
                f"{raw.get('source_platform', ''):12s}  {raw.get('risk_level', ''):6s}  "
                f"{raw.get('display_name', '')}"
            )
        except Exception as exc:
            typer.echo(f"  Error loading {yaml_file.name}: {exc}", err=True)


@app.command(name="template-info")
def template_info(name: str) -> None:
    """Show detailed information about a specific blueprint template."""
    template_file = TEMPLATE_DIR / f"{name.replace('-', '_')}.yaml"
    # Also try the name directly
    if not template_file.exists():
        template_file = TEMPLATE_DIR / f"{name}.yaml"
    # Try all files and match by name field
    if not template_file.exists():
        for f in TEMPLATE_DIR.glob("*.yaml"):
            raw = yaml.safe_load(f.read_text())
            if raw.get("name") == name:
                template_file = f
                break

    if not template_file.exists():
        typer.echo(f"Template not found: '{name}'", err=True)
        typer.echo("Use 'migrate templates' to see available templates.")
        raise typer.Exit(code=1)

    raw = yaml.safe_load(template_file.read_text())

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"  {raw['display_name']}")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"\n  Name:       {raw['name']}")
    typer.echo(f"  Category:   {raw.get('category', 'N/A')}")
    typer.echo(f"  Source:     {raw.get('source_platform', 'N/A')}")
    typer.echo(f"  Target:     {raw.get('target_platform', 'N/A')}")
    typer.echo(f"  Risk:       {raw.get('risk_level', 'N/A')}")
    typer.echo(f"  Duration:   {raw.get('estimated_duration', 'N/A')}")
    typer.echo(f"\n  Description:")
    typer.echo(f"    {raw.get('description', '').strip()}")

    typer.echo(f"\n  Prerequisites:")
    for prereq in raw.get("prerequisites", []):
        typer.echo(f"    - {prereq}")

    typer.echo(f"\n  Steps:")
    for i, step in enumerate(raw.get("steps", []), 1):
        typer.echo(f"    {i}. {step['description']} ({step['action']})")

    typer.echo(f"\n  Default Parameters:")
    for key, val in raw.get("parameters", {}).items():
        typer.echo(f"    {key}: {val}")
    typer.echo("")


@app.command(name="template-run")
def template_run(
    name: str,
    dry_run: bool = typer.Option(False, "--dry-run", help="Run template in dry-run mode"),
    skip_validation: bool = typer.Option(False, "--skip-validation", help="Skip validation"),
    poll: bool = typer.Option(True, help="Poll until job completes"),
) -> None:
    """Run a migration from a blueprint template."""
    # Find and load template
    template_raw = None
    for f in TEMPLATE_DIR.glob("*.yaml"):
        raw = yaml.safe_load(f.read_text())
        if raw.get("name") == name:
            template_raw = raw
            break

    if template_raw is None:
        typer.echo(f"Template not found: '{name}'", err=True)
        raise typer.Exit(code=1)

    adapter = template_raw["parameters"]["adapter"]
    typer.echo(f"\nRunning template: {template_raw['display_name']}")
    typer.echo(f"  Source: {template_raw['source_platform']}")
    typer.echo(f"  Target: {template_raw['target_platform']}")
    typer.echo(f"  Risk:   {template_raw.get('risk_level', 'N/A')}")

    if dry_run:
        typer.echo("  Mode:   DRY RUN")

    typer.echo(f"\n  Steps:")
    for i, step in enumerate(template_raw.get("steps", []), 1):
        typer.echo(f"    {i}. {step['description']}")

    typer.echo("")

    # Execute: find the 'execute' step and run it
    params = {}
    if skip_validation or template_raw["parameters"].get("skip_validation"):
        params["skip_validation"] = "true"
    if dry_run:
        params["dry_run"] = "true"

    typer.echo(f"Starting migration for '{adapter}'...")
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/execute/{adapter}", params=params)
    data = _handle_response(resp)

    job_id = data["job_id"]
    typer.echo(f"Job started: {job_id}")

    if not poll:
        typer.echo(f"Poll status with: migrate status {job_id}")
        return

    # Poll until done
    typer.echo("Waiting for completion...\n")
    with httpx.Client(timeout=10) as client:
        while True:
            time.sleep(0.5)
            resp = client.get(f"{_base_url()}/status/{job_id}")
            data = _handle_response(resp)
            status_val = data["status"]
            steps = ", ".join(data.get("steps_completed", []))
            typer.echo(f"  Status: {status_val:25s}  Steps: [{steps}]")

            if status_val in ("completed", "failed"):
                break

    typer.echo("")
    if data["status"] == "completed":
        typer.echo("Template migration completed successfully!")
        typer.echo(f"  Resources: {data['resource_count']}")
        if data.get("terraform_output"):
            typer.echo(f"  Terraform: {data['terraform_output']}")
        if data.get("migration_output_dir"):
            typer.echo(f"  Output:    {data['migration_output_dir']}")
    else:
        typer.echo(f"Template migration FAILED: {data.get('error', 'unknown')}", err=True)
        raise typer.Exit(code=1)


# --- Quickstart Command ---

@app.command()
def quickstart() -> None:
    """Interactive guided migration setup — choose a template and configure it."""
    typer.echo("\n  Migration Orchestration Engine — Quickstart\n")
    typer.echo("  This wizard will guide you through setting up a migration.\n")

    # Step 1: List available templates
    yaml_files = sorted(TEMPLATE_DIR.glob("*.yaml"))
    if not yaml_files:
        typer.echo("No templates available. Please add templates to the blueprints directory.", err=True)
        raise typer.Exit(code=1)

    template_list = []
    for yaml_file in yaml_files:
        raw = yaml.safe_load(yaml_file.read_text())
        template_list.append(raw)

    typer.echo("  Available migration templates:\n")
    for i, t in enumerate(template_list, 1):
        typer.echo(f"    {i}. {t['display_name']}")
        typer.echo(f"       Source: {t['source_platform']}  |  Risk: {t.get('risk_level', 'N/A')}  |  {t.get('estimated_duration', '')}")
        typer.echo("")

    # Step 2: Choose template
    choice = typer.prompt("  Select template number", type=int)
    if choice < 1 or choice > len(template_list):
        typer.echo("Invalid selection.", err=True)
        raise typer.Exit(code=1)

    selected = template_list[choice - 1]
    typer.echo(f"\n  Selected: {selected['display_name']}\n")

    # Step 3: Show prerequisites
    typer.echo("  Prerequisites:")
    for prereq in selected.get("prerequisites", []):
        typer.echo(f"    - {prereq}")

    proceed = typer.confirm("\n  Are all prerequisites met?", default=True)
    if not proceed:
        typer.echo("\n  Please complete prerequisites before continuing.")
        raise typer.Exit(code=0)

    # Step 4: Configure options
    typer.echo("\n  Configuration:\n")
    dry_run = typer.confirm("    Run as dry-run (simulation only)?", default=True)
    skip_val = typer.confirm("    Skip validation errors?", default=False)

    # Step 5: Confirm and execute
    typer.echo(f"\n  Summary:")
    typer.echo(f"    Template:        {selected['display_name']}")
    typer.echo(f"    Adapter:         {selected['parameters']['adapter']}")
    typer.echo(f"    Dry run:         {dry_run}")
    typer.echo(f"    Skip validation: {skip_val}")

    confirm = typer.confirm("\n  Proceed with migration?", default=True)
    if not confirm:
        typer.echo("  Cancelled.")
        raise typer.Exit(code=0)

    typer.echo("")

    # Execute via template-run
    params = {}
    if skip_val:
        params["skip_validation"] = "true"
    if dry_run:
        params["dry_run"] = "true"

    adapter = selected["parameters"]["adapter"]
    typer.echo(f"  Starting migration for '{adapter}'...")

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/execute/{adapter}", params=params)
    data = _handle_response(resp)

    job_id = data["job_id"]
    typer.echo(f"  Job started: {job_id}\n")

    # Poll
    typer.echo("  Waiting for completion...\n")
    with httpx.Client(timeout=10) as client:
        while True:
            time.sleep(0.5)
            resp = client.get(f"{_base_url()}/status/{job_id}")
            data = _handle_response(resp)
            status_val = data["status"]
            steps = ", ".join(data.get("steps_completed", []))
            typer.echo(f"    Status: {status_val:25s}  Steps: [{steps}]")

            if status_val in ("completed", "failed"):
                break

    typer.echo("")
    if data["status"] == "completed":
        typer.echo("  Migration completed successfully!")
        typer.echo(f"    Resources: {data['resource_count']}")
        if dry_run:
            typer.echo("    Mode: DRY RUN (no data was transferred)")
            typer.echo("\n  To run for real, repeat without --dry-run.")
    else:
        typer.echo(f"  Migration FAILED: {data.get('error', 'unknown')}", err=True)
        raise typer.Exit(code=1)


@app.command()
def resume(
    job_id: str,
    poll: bool = typer.Option(True, help="Poll until job completes"),
) -> None:
    """Resume a failed migration from its last checkpoint."""
    typer.echo(f"Resuming migration job: {job_id}")

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/resume/{job_id}")
    data = _handle_response(resp)

    typer.echo(f"Resume started: {data['job_id']}")

    if not poll:
        typer.echo(f"Poll status with: migrate status {data['job_id']}")
        return

    # Poll until done
    typer.echo("Waiting for completion...\n")
    with httpx.Client(timeout=10) as client:
        while True:
            time.sleep(0.5)
            resp = client.get(f"{_base_url()}/status/{data['job_id']}")
            poll_data = _handle_response(resp)
            status_val = poll_data["status"]
            steps = ", ".join(poll_data.get("steps_completed", []))
            typer.echo(f"  Status: {status_val:25s}  Steps: [{steps}]")

            if status_val in ("completed", "failed"):
                break

    typer.echo("")
    if poll_data["status"] == "completed":
        typer.echo("Migration resumed and completed successfully!")
    else:
        typer.echo(f"Resume FAILED: {poll_data.get('error', 'unknown')}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
