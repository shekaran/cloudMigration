"""Kubernetes backup/restore service — Velero-like abstraction for K8s workload migration.

Provides:
- Backup: Captures K8s resource specs and PVC snapshot metadata
- Restore: Generates restore manifests for the target cluster
- Validation: Compares source and target resources for completeness
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import KubernetesResource, StorageVolume
from app.models.k8s_target import K8sTranslationResult
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class PVCSnapshot(BaseModel):
    """Simulated snapshot of a PersistentVolumeClaim."""

    pvc_name: str = Field(description="PVC name")
    namespace: str = Field(description="Namespace")
    size_gb: int = Field(description="Volume size in GB")
    storage_class: str = Field(default="", description="Source storage class")
    snapshot_id: str = Field(description="Unique snapshot identifier")
    status: str = Field(default="completed", description="Snapshot status")


class KubernetesBackup(BaseModel):
    """A complete backup of a Kubernetes namespace/cluster."""

    backup_id: str = Field(description="Unique backup identifier")
    cluster_name: str = Field(default="", description="Source cluster")
    namespaces: list[str] = Field(default_factory=list, description="Backed up namespaces")
    created_at: str = Field(description="ISO timestamp")
    workload_specs: list[dict] = Field(
        default_factory=list, description="Captured workload specs (Deployments, StatefulSets)"
    )
    service_specs: list[dict] = Field(
        default_factory=list, description="Captured Service specs"
    )
    config_specs: list[dict] = Field(
        default_factory=list, description="ConfigMaps, Secrets (metadata only)"
    )
    pvc_snapshots: list[PVCSnapshot] = Field(
        default_factory=list, description="PVC snapshots"
    )
    resource_counts: dict[str, int] = Field(default_factory=dict)
    status: str = Field(default="completed")


class RestoreValidation(BaseModel):
    """Validation result comparing source backup to target restore."""

    backup_id: str = Field(description="Backup being validated")
    checks: list[dict] = Field(default_factory=list, description="Individual check results")
    passed: bool = Field(default=True)
    total_checks: int = Field(default=0)
    passed_checks: int = Field(default=0)
    failed_checks: int = Field(default=0)
    warnings: int = Field(default=0)


class K8sMigrationService:
    """Manages Kubernetes workload backup, restore, and validation.

    Pipeline:
    1. backup() — capture all resource specs and PVC snapshots from source
    2. restore() — generate target manifests from backup + translation
    3. validate() — verify target matches source (resource counts, replicas, PVCs)

    Args:
        output_dir: Base directory for backup/restore artifacts.
    """

    def __init__(self, output_dir: str | Path = "output/k8s") -> None:
        self._output_dir = Path(output_dir)

    def backup(self, canonical: DiscoveredResources) -> KubernetesBackup:
        """Create a backup from discovered K8s resources.

        Captures workload specs, service definitions, and PVC snapshots.
        Analogous to `velero backup create`.

        Args:
            canonical: Discovered resources from the K8s adapter.

        Returns:
            KubernetesBackup with all captured resource specs.
        """
        backup_id = f"backup-{uuid4().hex[:12]}"
        logger.info(
            "k8s_backup_started",
            backup_id=backup_id,
            workloads=len(canonical.kubernetes),
            pvcs=len(canonical.storage),
        )

        # Capture namespaces
        namespaces = list({w.namespace for w in canonical.kubernetes})

        # Capture workload specs
        workload_specs = []
        for w in canonical.kubernetes:
            workload_specs.append({
                "name": w.name,
                "kind": w.kind,
                "namespace": w.namespace,
                "replicas": w.replicas,
                "spec": w.spec,
                "labels": w.tags,
            })

        # Capture service specs from networks that are from kubernetes
        service_specs = []
        for net in canonical.networks:
            if net.platform == "kubernetes":
                service_specs.append({
                    "name": net.name,
                    "namespace": net.metadata.get("namespace", "default"),
                    "service_type": net.metadata.get("service_type", "ClusterIP"),
                    "ports": net.metadata.get("ports", []),
                    "selector": net.metadata.get("selector", {}),
                })

        # Capture config specs (metadata only for secrets)
        config_specs = []

        # Create PVC snapshots
        pvc_snapshots = []
        for vol in canonical.storage:
            if vol.platform == "kubernetes":
                pvc_snapshots.append(PVCSnapshot(
                    pvc_name=vol.name,
                    namespace=vol.metadata.get("namespace", "default"),
                    size_gb=vol.size_gb,
                    storage_class=vol.metadata.get("storage_class", ""),
                    snapshot_id=f"snap-{uuid4().hex[:12]}",
                ))

        cluster_name = ""
        if canonical.kubernetes:
            cluster_name = canonical.kubernetes[0].metadata.get("cluster", "")

        resource_counts = {
            "workloads": len(workload_specs),
            "services": len(service_specs),
            "pvcs": len(pvc_snapshots),
            "namespaces": len(namespaces),
        }

        backup = KubernetesBackup(
            backup_id=backup_id,
            cluster_name=cluster_name,
            namespaces=namespaces,
            created_at=datetime.now(timezone.utc).isoformat(),
            workload_specs=workload_specs,
            service_specs=service_specs,
            config_specs=config_specs,
            pvc_snapshots=pvc_snapshots,
            resource_counts=resource_counts,
        )

        # Write backup to disk
        self._write_backup(backup)

        logger.info(
            "k8s_backup_completed",
            backup_id=backup_id,
            resource_counts=resource_counts,
        )
        return backup

    def restore(
        self,
        backup: KubernetesBackup,
        translation: K8sTranslationResult,
    ) -> Path:
        """Generate restore manifests from a backup and translation result.

        Writes YAML-like manifests to disk for each translated resource.
        Analogous to `velero restore create --from-backup`.

        Args:
            backup: The source backup to restore from.
            translation: Translated target resources.

        Returns:
            Path to the restore output directory.
        """
        restore_id = f"restore-{uuid4().hex[:12]}"
        restore_dir = self._output_dir / "restores" / restore_id
        restore_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "k8s_restore_started",
            restore_id=restore_id,
            backup_id=backup.backup_id,
            target_platform=translation.cluster.platform.value,
        )

        # Write cluster config
        (restore_dir / "cluster.json").write_text(
            json.dumps(translation.cluster.model_dump(mode="json"), indent=2, default=str)
        )

        # Write namespace manifests
        ns_dir = restore_dir / "namespaces"
        ns_dir.mkdir(exist_ok=True)
        for ns in translation.namespaces:
            (ns_dir / f"{ns.name}.json").write_text(
                json.dumps({"apiVersion": "v1", "kind": "Namespace", "metadata": {
                    "name": ns.name, "labels": ns.labels,
                }}, indent=2)
            )

        # Write workload manifests
        wl_dir = restore_dir / "workloads"
        wl_dir.mkdir(exist_ok=True)
        for wl in translation.workloads:
            (wl_dir / f"{wl.name}.json").write_text(
                json.dumps(wl.manifest, indent=2, default=str)
            )

        # Write service manifests
        svc_dir = restore_dir / "services"
        svc_dir.mkdir(exist_ok=True)
        for svc in translation.services:
            (svc_dir / f"{svc.name}.json").write_text(
                json.dumps(svc.manifest, indent=2, default=str)
            )

        # Write storage manifests
        stor_dir = restore_dir / "storage"
        stor_dir.mkdir(exist_ok=True)
        for pvc in translation.storage:
            (stor_dir / f"{pvc.name}.json").write_text(
                json.dumps(pvc.manifest, indent=2, default=str)
            )

        # Write restore manifest
        restore_manifest = {
            "restore_id": restore_id,
            "backup_id": backup.backup_id,
            "target_cluster": translation.cluster.name,
            "target_platform": translation.cluster.platform.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resources_restored": {
                "namespaces": len(translation.namespaces),
                "workloads": len(translation.workloads),
                "services": len(translation.services),
                "storage": len(translation.storage),
            },
            "status": "completed",
        }
        (restore_dir / "restore-manifest.json").write_text(
            json.dumps(restore_manifest, indent=2)
        )

        logger.info(
            "k8s_restore_completed",
            restore_id=restore_id,
            output_dir=str(restore_dir),
            workloads=len(translation.workloads),
            services=len(translation.services),
            storage=len(translation.storage),
        )
        return restore_dir

    def validate(
        self,
        backup: KubernetesBackup,
        translation: K8sTranslationResult,
    ) -> RestoreValidation:
        """Validate that the translation covers all backed-up resources.

        Checks:
        - All workloads are translated
        - Replica counts match
        - All PVCs have target storage
        - All services are translated
        - Storage sizes are preserved

        Args:
            backup: Source backup.
            translation: Target translation result.

        Returns:
            RestoreValidation with pass/fail status and detailed checks.
        """
        logger.info(
            "k8s_validation_started",
            backup_id=backup.backup_id,
        )

        checks: list[dict] = []

        # Check 1: Namespace coverage
        source_ns = set(backup.namespaces)
        target_ns = {ns.name for ns in translation.namespaces}
        missing_ns = source_ns - target_ns
        checks.append({
            "check": "namespace_coverage",
            "passed": len(missing_ns) == 0,
            "severity": "ERROR" if missing_ns else "INFO",
            "message": f"Missing namespaces: {missing_ns}" if missing_ns
                else f"All {len(source_ns)} namespaces covered",
        })

        # Check 2: Workload coverage
        source_wl_names = {w["name"] for w in backup.workload_specs}
        target_wl_names = {w.name for w in translation.workloads}
        missing_wl = source_wl_names - target_wl_names
        checks.append({
            "check": "workload_coverage",
            "passed": len(missing_wl) == 0,
            "severity": "ERROR" if missing_wl else "INFO",
            "message": f"Missing workloads: {missing_wl}" if missing_wl
                else f"All {len(source_wl_names)} workloads translated",
        })

        # Check 3: Replica counts
        for src_wl in backup.workload_specs:
            tgt = next((w for w in translation.workloads if w.name == src_wl["name"]), None)
            if tgt and src_wl.get("replicas") is not None:
                match = tgt.replicas == src_wl["replicas"]
                checks.append({
                    "check": f"replica_count_{src_wl['name']}",
                    "passed": match,
                    "severity": "WARNING" if not match else "INFO",
                    "message": f"{src_wl['name']}: source={src_wl['replicas']} target={tgt.replicas}",
                })

        # Check 4: PVC coverage
        source_pvc_names = {s.pvc_name for s in backup.pvc_snapshots}
        target_pvc_names = {s.name for s in translation.storage}
        missing_pvcs = source_pvc_names - target_pvc_names
        checks.append({
            "check": "pvc_coverage",
            "passed": len(missing_pvcs) == 0,
            "severity": "ERROR" if missing_pvcs else "INFO",
            "message": f"Missing PVCs: {missing_pvcs}" if missing_pvcs
                else f"All {len(source_pvc_names)} PVCs covered",
        })

        # Check 5: Storage size preservation
        for snap in backup.pvc_snapshots:
            tgt = next((s for s in translation.storage if s.name == snap.pvc_name), None)
            if tgt:
                match = tgt.size_gb >= snap.size_gb
                checks.append({
                    "check": f"storage_size_{snap.pvc_name}",
                    "passed": match,
                    "severity": "ERROR" if not match else "INFO",
                    "message": f"{snap.pvc_name}: source={snap.size_gb}Gi target={tgt.size_gb}Gi",
                })

        # Check 6: Service coverage
        source_svc_names = {s["name"] for s in backup.service_specs}
        target_svc_names = {s.name for s in translation.services}
        missing_svcs = source_svc_names - target_svc_names
        checks.append({
            "check": "service_coverage",
            "passed": len(missing_svcs) == 0,
            "severity": "ERROR" if missing_svcs else "INFO",
            "message": f"Missing services: {missing_svcs}" if missing_svcs
                else f"All {len(source_svc_names)} services translated",
        })

        total = len(checks)
        passed = sum(1 for c in checks if c["passed"])
        failed = sum(1 for c in checks if not c["passed"] and c["severity"] == "ERROR")
        warnings = sum(1 for c in checks if not c["passed"] and c["severity"] == "WARNING")

        result = RestoreValidation(
            backup_id=backup.backup_id,
            checks=checks,
            passed=failed == 0,
            total_checks=total,
            passed_checks=passed,
            failed_checks=failed,
            warnings=warnings,
        )

        logger.info(
            "k8s_validation_completed",
            backup_id=backup.backup_id,
            passed=result.passed,
            total_checks=total,
            failed=failed,
            warnings=warnings,
        )
        return result

    def _write_backup(self, backup: KubernetesBackup) -> None:
        """Write backup artifacts to disk."""
        backup_dir = self._output_dir / "backups" / backup.backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        (backup_dir / "backup-manifest.json").write_text(
            json.dumps(backup.model_dump(), indent=2, default=str)
        )

        for wl in backup.workload_specs:
            wl_dir = backup_dir / "workloads"
            wl_dir.mkdir(exist_ok=True)
            (wl_dir / f"{wl['name']}.json").write_text(
                json.dumps(wl, indent=2, default=str)
            )
