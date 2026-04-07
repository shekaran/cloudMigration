"""Blueprint engine — loads, validates, and executes migration blueprints.

Provides:
1. Template registry — discovers and loads YAML blueprint templates
2. Blueprint validation — validates parameters and prerequisites
3. Guided workflow — step-by-step execution with user confirmation points
"""

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


class BlueprintStep(BaseModel):
    """A single step in a blueprint workflow."""

    name: str = Field(description="Step identifier")
    description: str = Field(description="Human-readable description")
    action: str = Field(description="Action to execute (discover, validate, plan, execute)")
    params: dict[str, str] = Field(default_factory=dict, description="Step parameters (may contain template vars)")


class BlueprintTemplate(BaseModel):
    """A prebuilt migration blueprint template."""

    name: str = Field(description="Unique template identifier (slug)")
    display_name: str = Field(description="Human-readable template name")
    description: str = Field(description="Detailed description of what this template does")
    version: str = Field(default="1.0")
    category: str = Field(description="Migration category (lift_and_shift, replatform, rebuild, kubernetes)")
    source_platform: str = Field(description="Source platform adapter name")
    target_platform: str = Field(description="Target platform identifier")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Default parameter values")
    steps: list[BlueprintStep] = Field(default_factory=list, description="Ordered workflow steps")
    prerequisites: list[str] = Field(default_factory=list, description="Required preconditions")
    estimated_duration: str = Field(default="", description="Estimated time to complete")
    risk_level: str = Field(default="medium", description="Risk level (low, medium, high)")


class BlueprintInstance(BaseModel):
    """A configured blueprint ready for execution."""

    template_name: str = Field(description="Source template name")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Resolved parameters")
    steps: list[BlueprintStep] = Field(default_factory=list, description="Steps with resolved params")
    current_step: int = Field(default=0, description="Index of the current/next step to execute")
    completed_steps: list[str] = Field(default_factory=list, description="Names of completed steps")
    status: str = Field(default="pending", description="Overall status")


class BlueprintEngine:
    """Manages blueprint templates and guided migration workflows.

    Usage:
        engine = BlueprintEngine()
        templates = engine.list_templates()
        template = engine.get_template("lift-and-shift-vmware")
        instance = engine.configure(template, overrides={"dry_run": True})
        # Execute steps one at a time or all at once via CLI/API
    """

    def __init__(self, template_dir: Path = TEMPLATE_DIR) -> None:
        self._template_dir = template_dir
        self._templates: dict[str, BlueprintTemplate] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Discover and load all YAML blueprint templates."""
        if not self._template_dir.exists():
            logger.warning("blueprint_template_dir_missing", path=str(self._template_dir))
            return

        for yaml_file in sorted(self._template_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_file.read_text())
                # Convert step dicts to BlueprintStep models
                steps = [
                    BlueprintStep(**step) for step in raw.pop("steps", [])
                ]
                template = BlueprintTemplate(**raw, steps=steps)
                self._templates[template.name] = template

                logger.info(
                    "blueprint_template_loaded",
                    name=template.name,
                    category=template.category,
                    steps=len(template.steps),
                )
            except Exception as exc:
                logger.error(
                    "blueprint_template_load_failed",
                    file=str(yaml_file),
                    error=str(exc),
                )

    def list_templates(self) -> list[BlueprintTemplate]:
        """Return all available blueprint templates."""
        return list(self._templates.values())

    def get_template(self, name: str) -> BlueprintTemplate | None:
        """Get a template by name."""
        return self._templates.get(name)

    def list_by_category(self, category: str) -> list[BlueprintTemplate]:
        """Filter templates by category."""
        return [t for t in self._templates.values() if t.category == category]

    def list_by_platform(self, platform: str) -> list[BlueprintTemplate]:
        """Filter templates by source platform."""
        return [t for t in self._templates.values() if t.source_platform == platform]

    def configure(
        self,
        template: BlueprintTemplate,
        overrides: dict[str, Any] | None = None,
    ) -> BlueprintInstance:
        """Create a configured blueprint instance ready for execution.

        Merges template defaults with user overrides and resolves
        template variables in step parameters.
        """
        params = {**template.parameters}
        if overrides:
            params.update(overrides)

        # Resolve template variables in step params
        resolved_steps: list[BlueprintStep] = []
        for step in template.steps:
            resolved_params = {}
            for key, value in step.params.items():
                resolved_params[key] = self._resolve_param(value, params)
            resolved_steps.append(BlueprintStep(
                name=step.name,
                description=step.description,
                action=step.action,
                params=resolved_params,
            ))

        instance = BlueprintInstance(
            template_name=template.name,
            parameters=params,
            steps=resolved_steps,
        )

        logger.info(
            "blueprint_configured",
            template=template.name,
            overrides=list((overrides or {}).keys()),
            steps=len(resolved_steps),
        )
        return instance

    def advance_step(self, instance: BlueprintInstance) -> BlueprintStep | None:
        """Get the next step to execute and advance the cursor.

        Returns None if all steps are completed.
        """
        if instance.current_step >= len(instance.steps):
            instance.status = "completed"
            return None

        step = instance.steps[instance.current_step]
        return step

    def complete_step(self, instance: BlueprintInstance, step_name: str) -> None:
        """Mark a step as completed and advance to the next."""
        instance.completed_steps.append(step_name)
        instance.current_step += 1
        instance.status = "in_progress"

        if instance.current_step >= len(instance.steps):
            instance.status = "completed"

        logger.info(
            "blueprint_step_completed",
            template=instance.template_name,
            step=step_name,
            progress=f"{instance.current_step}/{len(instance.steps)}",
        )

    def get_prerequisites(self, template: BlueprintTemplate) -> list[str]:
        """Return the prerequisites for a template."""
        return template.prerequisites

    def validate_parameters(
        self,
        template: BlueprintTemplate,
        params: dict[str, Any],
    ) -> list[str]:
        """Validate parameters against template requirements.

        Returns a list of validation error messages (empty if valid).
        """
        errors: list[str] = []

        # Check that adapter parameter matches the template's source platform
        if "adapter" in params:
            if params["adapter"] != template.source_platform:
                errors.append(
                    f"Adapter '{params['adapter']}' does not match template's "
                    f"source platform '{template.source_platform}'"
                )

        return errors

    @staticmethod
    def _resolve_param(value: str, params: dict[str, Any]) -> str:
        """Resolve {{ variable }} placeholders in a parameter value."""
        if not isinstance(value, str):
            return str(value)

        result = value
        for key, val in params.items():
            placeholder = "{{ " + key + " }}"
            if placeholder in result:
                result = result.replace(placeholder, str(val))
        return result
