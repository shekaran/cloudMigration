"""Terraform code generator — renders VPC translation results into .tf files."""

import os
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader

from app.models.vpc import VPCTranslationResult

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_OUTPUT_DIR = Path("output/terraform")


class TerraformGenerator:
    """Generates Terraform HCL files from a VPCTranslationResult using Jinja2 templates."""

    def __init__(self, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def generate(self, result: VPCTranslationResult) -> Path:
        """Render Terraform code and write to output directory.

        Args:
            result: Complete VPC translation result.

        Returns:
            Path to the generated main.tf file.
        """
        logger.info(
            "terraform_generation_started",
            output_dir=str(self._output_dir),
            resource_count=result.resource_count,
        )

        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Build template context with resolved cross-references
        context = self._build_context(result)

        template = self._env.get_template("main.tf.j2")
        rendered = template.render(**context)

        output_file = self._output_dir / "main.tf"
        output_file.write_text(rendered)

        logger.info(
            "terraform_generation_completed",
            output_file=str(output_file),
            size_bytes=os.path.getsize(output_file),
        )
        return output_file

    def _build_context(self, result: VPCTranslationResult) -> dict:
        """Build the Jinja2 template context, resolving UUID references to names."""
        # Map subnet IDs → names for instance reference
        subnet_name_by_id = {s.id: s.name for s in result.subnets}
        sg_name_by_id = {sg.id: sg.name for sg in result.security_groups}

        # Enrich instances with resolved names for Terraform references
        instances = []
        for inst in result.instances:
            inst_dict = inst.model_dump()
            inst_dict["subnet_name"] = subnet_name_by_id.get(inst.subnet_id, "unknown")
            inst_dict["security_group_names"] = [
                sg_name_by_id[sg_id]
                for sg_id in inst.security_group_ids
                if sg_id in sg_name_by_id
            ]
            instances.append(inst_dict)

        return {
            "vpc": result.vpc,
            "subnets": result.subnets,
            "security_groups": result.security_groups,
            "instances": instances,
        }
