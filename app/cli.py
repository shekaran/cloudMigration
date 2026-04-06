"""CLI tool for the Migration Orchestration Engine — hits the running API via HTTP."""

import json
import time

import httpx
import typer

app = typer.Typer(
    name="migrate",
    help="Migration Orchestration Engine CLI — interact with the running API.",
)

DEFAULT_BASE_URL = "http://localhost:8000"


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
def execute(adapter: str, poll: bool = typer.Option(True, help="Poll until job completes")) -> None:
    """Execute a full migration for a source platform (async)."""
    typer.echo(f"Starting migration for '{adapter}'...")
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/execute/{adapter}")
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


@app.command()
def jobs() -> None:
    """List all migration jobs."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{_base_url()}/jobs")
    data = _handle_response(resp)

    if not data:
        typer.echo("No jobs found.")
        return

    typer.echo(f"{'JOB ID':38s}  {'ADAPTER':15s}  {'STATUS':20s}  {'RESOURCES':>9s}")
    typer.echo("-" * 90)
    for job in data:
        typer.echo(
            f"{job['job_id']:38s}  {job['adapter']:15s}  "
            f"{job['status']:20s}  {job['resource_count']:>9d}"
        )


if __name__ == "__main__":
    app()
