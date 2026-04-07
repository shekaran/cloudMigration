"""Kubernetes adapter — discovers workloads, services, and storage from a K8s cluster."""

from typing import Any
from uuid import UUID

import structlog

from app.adapters.base import AbstractBaseAdapter
from app.adapters.kubernetes.mock_data import K8S_MOCK_DATA
from app.models.canonical import (
    KubernetesResource,
    NetworkSegment,
    NetworkType,
    SecurityPolicy,
    SecurityPolicyType,
    SecurityRule,
    StorageVolume,
    StorageType,
    ProtocolType,
)
from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


def _parse_resource_quantity(value: str) -> int:
    """Parse K8s resource quantity (e.g., '2Gi', '500m', '4') to a numeric value.

    For memory: returns megabytes.
    For CPU: returns millicores.
    """
    if not value:
        return 0
    value = value.strip()
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return int(float(value[:-2]))
    if value.endswith("Ki"):
        return int(float(value[:-2]) / 1024)
    if value.endswith("m"):
        return int(value[:-1])
    # Plain integer — CPU cores → millicores, or raw number
    try:
        return int(float(value) * 1000) if "." not in value and int(value) < 1000 else int(value)
    except ValueError:
        return 0


def _parse_storage_gi(value: str) -> int:
    """Parse K8s storage quantity to GB."""
    if not value:
        return 0
    value = value.strip()
    if value.endswith("Gi"):
        return int(float(value[:-2]))
    if value.endswith("Ti"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Mi"):
        return max(1, int(float(value[:-2]) / 1024))
    return 0


class KubernetesAdapter(AbstractBaseAdapter):
    """Adapter for Kubernetes clusters (workloads, services, storage)."""

    @property
    def platform_name(self) -> str:
        return "kubernetes"

    async def discover(self) -> dict[str, Any]:
        """Return mocked Kubernetes API data."""
        logger.info("discovery_started", platform=self.platform_name)
        raw_data = K8S_MOCK_DATA
        cluster = raw_data.get("cluster", {})
        logger.info(
            "discovery_completed",
            platform=self.platform_name,
            cluster=cluster.get("name", ""),
            k8s_version=cluster.get("version", ""),
            deployments=len(raw_data.get("deployments", [])),
            services=len(raw_data.get("services", [])),
            pvcs=len(raw_data.get("pvcs", [])),
            configmaps=len(raw_data.get("configmaps", [])),
        )
        return raw_data

    def normalize(self, raw_data: dict[str, Any]) -> DiscoveredResources:
        """Convert raw K8s API data into canonical models."""
        logger.info("normalization_started", platform=self.platform_name)

        kubernetes = self._normalize_workloads(raw_data)
        storage = self._normalize_pvcs(raw_data.get("pvcs", []))
        networks = self._normalize_services(raw_data.get("services", []))
        security_policies = self._normalize_network_policies(raw_data)

        # Build cross-references
        k8s_by_name: dict[str, KubernetesResource] = {r.name: r for r in kubernetes}
        storage_by_name: dict[str, StorageVolume] = {v.name: v for v in storage}
        svc_by_name: dict[str, NetworkSegment] = {n.name: n for n in networks}

        # Link workloads → PVCs (via volume mounts)
        for resource in kubernetes:
            volumes = resource.spec.get("template", {}).get("spec", {}).get("volumes", [])
            for vol in volumes:
                pvc_ref = vol.get("persistentVolumeClaim", {}).get("claimName", "")
                if pvc_ref and pvc_ref in storage_by_name:
                    pv = storage_by_name[pvc_ref]
                    pv.attached_to = resource.id
                    resource.dependencies.append(ResourceDependency(
                        source_id=resource.id,
                        target_id=pv.id,
                        dependency_type=DependencyType.STORAGE,
                        description=f"{resource.name} uses PVC {pvc_ref}",
                    ))

        # Link workloads → services (via selector match)
        for svc_raw in raw_data.get("services", []):
            svc_name = svc_raw["metadata"]["name"]
            svc_selector = svc_raw.get("spec", {}).get("selector", {})
            svc = svc_by_name.get(svc_name)
            if not svc:
                continue
            for resource in kubernetes:
                res_labels = resource.spec.get("selector", {}).get("matchLabels", {})
                if svc_selector and all(
                    res_labels.get(k) == v for k, v in svc_selector.items()
                ):
                    if resource.id not in svc.connected_resources:
                        svc.connected_resources.append(resource.id)
                    resource.dependencies.append(ResourceDependency(
                        source_id=resource.id,
                        target_id=svc.id,
                        dependency_type=DependencyType.NETWORK,
                        description=f"{resource.name} exposed by service {svc_name}",
                    ))

        # Link app-backend → postgres-db dependency (env var reference)
        app = k8s_by_name.get("app-backend")
        db = k8s_by_name.get("postgres-db")
        if app and db:
            app.dependencies.append(ResourceDependency(
                source_id=app.id,
                target_id=db.id,
                dependency_type=DependencyType.RUNTIME,
                description="app-backend depends on postgres-db via DB_HOST env",
            ))

        result = DiscoveredResources(
            kubernetes=kubernetes,
            networks=networks,
            security_policies=security_policies,
            storage=storage,
        )
        logger.info(
            "normalization_completed",
            platform=self.platform_name,
            total_resources=result.resource_count,
            workloads=len(kubernetes),
            services=len(networks),
            pvcs=len(storage),
        )
        return result

    def translate(self, canonical: DiscoveredResources) -> dict[str, Any]:
        """Stub — full translation via K8sTranslationService."""
        logger.info("translate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_4"}

    def migrate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Stub — full migration via Orchestrator."""
        logger.info("migrate_stub_called", platform=self.platform_name)
        return {"status": "not_implemented", "phase": "phase_4"}

    # --- Private helpers ---

    def _normalize_workloads(self, raw_data: dict) -> list[KubernetesResource]:
        """Normalize Deployments and StatefulSets into KubernetesResource."""
        results: list[KubernetesResource] = []
        cluster = raw_data.get("cluster", {})

        for deploy in raw_data.get("deployments", []):
            metadata = deploy.get("metadata", {})
            spec = deploy.get("spec", {})
            status = deploy.get("status", {})
            kind = deploy.get("kind", "Deployment")
            labels = metadata.get("labels", {})

            results.append(KubernetesResource(
                name=metadata.get("name", "unknown"),
                platform=self.platform_name,
                region=cluster.get("region", ""),
                kind=kind,
                namespace=metadata.get("namespace", "default"),
                spec=spec,
                replicas=spec.get("replicas"),
                tags=labels,
                metadata={
                    "cluster": cluster.get("name", ""),
                    "k8s_version": cluster.get("version", ""),
                    "kind": kind,
                    "ready_replicas": status.get("readyReplicas", 0),
                    "available_replicas": status.get("availableReplicas", 0),
                    "containers": [
                        {
                            "name": c.get("name", ""),
                            "image": c.get("image", ""),
                            "ports": c.get("ports", []),
                            "resources": c.get("resources", {}),
                        }
                        for c in spec.get("template", {})
                        .get("spec", {})
                        .get("containers", [])
                    ],
                },
            ))
        return results

    def _normalize_services(self, services: list[dict]) -> list[NetworkSegment]:
        """Normalize K8s Services into NetworkSegment."""
        results: list[NetworkSegment] = []
        for svc in services:
            metadata = svc.get("metadata", {})
            spec = svc.get("spec", {})
            svc_type = spec.get("type", "ClusterIP")
            labels = metadata.get("labels", {})

            # Map service type to network type
            net_type = NetworkType.VPC if svc_type == "LoadBalancer" else NetworkType.SUBNET

            # Build a representative CIDR (services don't have CIDRs, use cluster IP range)
            cluster_ip = "10.96.0.0/16"  # Default K8s service CIDR

            ports = spec.get("ports", [])
            port_list = [f"{p.get('port', 0)}/{p.get('protocol', 'TCP')}" for p in ports]

            results.append(NetworkSegment(
                name=metadata.get("name", "unknown"),
                platform=self.platform_name,
                type=net_type,
                cidr=cluster_ip,
                zone=labels.get("tier", ""),
                tags=labels,
                metadata={
                    "namespace": metadata.get("namespace", "default"),
                    "service_type": svc_type,
                    "ports": port_list,
                    "selector": spec.get("selector", {}),
                },
            ))
        return results

    def _normalize_pvcs(self, pvcs: list[dict]) -> list[StorageVolume]:
        """Normalize PersistentVolumeClaims into StorageVolume."""
        results: list[StorageVolume] = []
        for pvc in pvcs:
            metadata = pvc.get("metadata", {})
            spec = pvc.get("spec", {})
            status = pvc.get("status", {})
            labels = metadata.get("labels", {})

            storage_str = spec.get("resources", {}).get("requests", {}).get("storage", "0Gi")
            size_gb = _parse_storage_gi(storage_str)
            if size_gb < 1:
                size_gb = 1

            results.append(StorageVolume(
                name=metadata.get("name", "unknown"),
                platform=self.platform_name,
                type=StorageType.BLOCK,
                size_gb=size_gb,
                tags=labels,
                metadata={
                    "namespace": metadata.get("namespace", "default"),
                    "storage_class": spec.get("storageClassName", ""),
                    "access_modes": spec.get("accessModes", []),
                    "phase": status.get("phase", ""),
                },
            ))
        return results

    def _normalize_network_policies(self, raw_data: dict) -> list[SecurityPolicy]:
        """Generate a default security policy from services (implicit K8s network rules).

        K8s clusters without explicit NetworkPolicies have allow-all between pods.
        We generate a policy that reflects the service-level access patterns.
        """
        services = raw_data.get("services", [])
        if not services:
            return []

        rules: list[SecurityRule] = []
        for svc in services:
            spec = svc.get("spec", {})
            svc_name = svc.get("metadata", {}).get("name", "unknown")
            svc_type = spec.get("type", "ClusterIP")

            for port_spec in spec.get("ports", []):
                port = port_spec.get("port")
                protocol_raw = port_spec.get("protocol", "TCP").lower()
                try:
                    protocol = ProtocolType(protocol_raw)
                except ValueError:
                    protocol = ProtocolType.TCP

                # Source depends on service type
                source = "0.0.0.0/0" if svc_type == "LoadBalancer" else "10.96.0.0/16"

                rules.append(SecurityRule(
                    source=source,
                    destination="10.96.0.0/16",
                    port=port,
                    protocol=protocol,
                    action="allow",
                    direction="inbound",
                    priority=len(rules) + 1,
                ))

        return [SecurityPolicy(
            name="k8s-service-access",
            platform=self.platform_name,
            type=SecurityPolicyType.SECURITY_GROUP,
            rules=rules,
            metadata={
                "generated_from": "kubernetes_services",
                "description": "Implicit service-level access rules",
            },
        )]
