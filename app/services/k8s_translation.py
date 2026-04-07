"""Kubernetes translation service — converts canonical K8s resources to IKS or OpenShift targets."""

from __future__ import annotations

import structlog

from app.models.canonical import KubernetesResource
from app.models.k8s_target import (
    K8sTargetCluster,
    K8sTargetNamespace,
    K8sTargetPlatform,
    K8sTargetService,
    K8sTargetStorage,
    K8sTargetWorkload,
    K8sTranslationResult,
)
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)

# Storage class mappings per target platform
STORAGE_CLASS_MAP: dict[str, dict[str, str]] = {
    "iks": {
        "standard": "ibmc-vpc-block-5iops-tier",
        "fast-ssd": "ibmc-vpc-block-10iops-tier",
        "": "ibmc-vpc-block-5iops-tier",
    },
    "openshift": {
        "standard": "ocs-storagecluster-ceph-rbd",
        "fast-ssd": "ocs-storagecluster-ceph-rbd",
        "": "ocs-storagecluster-ceph-rbd",
    },
}

# Image registry prefix per target platform
REGISTRY_PREFIX: dict[str, str] = {
    "iks": "us.icr.io/migration",
    "openshift": "image-registry.openshift-image-registry.svc:5000/migration",
}

# K8s version per target platform
TARGET_VERSIONS: dict[str, str] = {
    "iks": "1.29",
    "openshift": "4.14",
}


class K8sTranslationService:
    """Translates canonical K8s resources into IKS or OpenShift target manifests.

    Supports configurable target platform (IKS or OpenShift) which affects:
    - Storage class mappings
    - Image registry prefixes
    - Cluster version
    - OpenShift-specific annotations (Routes instead of Ingress, etc.)

    Args:
        target_platform: "iks" or "openshift". Defaults to "iks".
        cluster_name: Target cluster name. Defaults to "migration-cluster".
        region: IBM Cloud region. Defaults to "us-south".
    """

    def __init__(
        self,
        target_platform: str = "iks",
        cluster_name: str = "migration-cluster",
        region: str = "us-south",
    ) -> None:
        try:
            self._platform = K8sTargetPlatform(target_platform)
        except ValueError:
            self._platform = K8sTargetPlatform.IKS
        self._cluster_name = cluster_name
        self._region = region

    def translate(self, canonical: DiscoveredResources) -> K8sTranslationResult:
        """Convert canonical K8s resources to target cluster manifests.

        Args:
            canonical: Discovered resources containing K8s workloads.

        Returns:
            K8sTranslationResult with cluster, namespaces, workloads, services, storage.
        """
        logger.info(
            "k8s_translation_started",
            platform=self._platform.value,
            workloads=len(canonical.kubernetes),
            services=len(canonical.networks),
            pvcs=len(canonical.storage),
        )

        cluster = self._create_cluster()
        namespaces = self._translate_namespaces(canonical.kubernetes, cluster)
        workloads = self._translate_workloads(canonical.kubernetes)
        services = self._translate_services(canonical.networks)
        storage = self._translate_storage(canonical.storage)

        result = K8sTranslationResult(
            cluster=cluster,
            namespaces=namespaces,
            workloads=workloads,
            services=services,
            storage=storage,
        )

        logger.info(
            "k8s_translation_completed",
            platform=self._platform.value,
            cluster=cluster.name,
            workloads=len(workloads),
            services=len(services),
            storage=len(storage),
        )
        return result

    def _create_cluster(self) -> K8sTargetCluster:
        """Create target cluster configuration."""
        return K8sTargetCluster(
            name=self._cluster_name,
            platform=self._platform,
            region=self._region,
            version=TARGET_VERSIONS.get(self._platform.value, "1.29"),
        )

    def _translate_namespaces(
        self,
        workloads: list[KubernetesResource],
        cluster: K8sTargetCluster,
    ) -> list[K8sTargetNamespace]:
        """Extract unique namespaces from workloads."""
        seen: dict[str, K8sTargetNamespace] = {}
        for w in workloads:
            ns = w.namespace
            if ns not in seen:
                seen[ns] = K8sTargetNamespace(
                    name=ns,
                    cluster_id=cluster.id,
                    labels={"migrated-from": w.platform},
                    source_namespace=ns,
                )
        return list(seen.values())

    def _translate_workloads(
        self, workloads: list[KubernetesResource]
    ) -> list[K8sTargetWorkload]:
        """Translate K8s workloads to target manifests."""
        results: list[K8sTargetWorkload] = []

        for w in workloads:
            kind = w.kind
            containers = w.metadata.get("containers", [])
            spec = w.spec

            # Translate container images (prefix with target registry)
            translated_containers = []
            for c in containers:
                image = c.get("image", "")
                # Preserve public images (nginx, postgres, etc.), prefix custom ones
                if "/" in image and not image.startswith(("docker.io", "gcr.io", "quay.io")):
                    registry = REGISTRY_PREFIX.get(self._platform.value, "")
                    image = f"{registry}/{image.split('/')[-1]}"

                translated_containers.append({
                    "name": c.get("name", ""),
                    "image": image,
                    "ports": c.get("ports", []),
                    "resources": c.get("resources", {}),
                })

            # Build full manifest
            manifest = self._build_workload_manifest(
                w.name, kind, w.namespace, w.replicas or 1,
                translated_containers, spec, w.tags,
            )

            results.append(K8sTargetWorkload(
                name=w.name,
                kind=kind,
                namespace=w.namespace,
                replicas=w.replicas or 1,
                containers=translated_containers,
                volumes=spec.get("template", {}).get("spec", {}).get("volumes", []),
                labels=w.tags,
                source_workload_name=w.name,
                manifest=manifest,
            ))

        return results

    def _translate_services(
        self, networks: list
    ) -> list[K8sTargetService]:
        """Translate service-derived NetworkSegments back to K8s Service manifests."""
        results: list[K8sTargetService] = []

        for net in networks:
            if net.platform != "kubernetes":
                continue

            svc_type = net.metadata.get("service_type", "ClusterIP")
            namespace = net.metadata.get("namespace", "default")
            selector = net.metadata.get("selector", {})
            port_strs = net.metadata.get("ports", [])

            # Parse port strings back to port specs
            ports = []
            for ps in port_strs:
                parts = ps.split("/")
                port_num = int(parts[0]) if parts[0].isdigit() else 80
                protocol = parts[1] if len(parts) > 1 else "TCP"
                ports.append({
                    "port": port_num,
                    "targetPort": port_num,
                    "protocol": protocol,
                })

            # For OpenShift LoadBalancer → Route
            if self._platform == K8sTargetPlatform.OPENSHIFT and svc_type == "LoadBalancer":
                svc_type = "ClusterIP"  # OpenShift uses Routes instead

            manifest = self._build_service_manifest(
                net.name, namespace, svc_type, ports, selector,
            )

            results.append(K8sTargetService(
                name=net.name,
                namespace=namespace,
                service_type=svc_type,
                ports=ports,
                selector=selector,
                source_service_name=net.name,
                manifest=manifest,
            ))

        return results

    def _translate_storage(self, storage: list) -> list[K8sTargetStorage]:
        """Translate PVC-derived StorageVolumes to target PVC manifests."""
        results: list[K8sTargetStorage] = []

        for vol in storage:
            if vol.platform != "kubernetes":
                continue

            source_class = vol.metadata.get("storage_class", "")
            platform_key = self._platform.value
            target_class = STORAGE_CLASS_MAP.get(platform_key, {}).get(
                source_class, STORAGE_CLASS_MAP[platform_key][""]
            )

            namespace = vol.metadata.get("namespace", "default")
            access_modes = vol.metadata.get("access_modes", ["ReadWriteOnce"])

            manifest = self._build_pvc_manifest(
                vol.name, namespace, target_class, vol.size_gb, access_modes,
            )

            results.append(K8sTargetStorage(
                name=vol.name,
                namespace=namespace,
                storage_class=target_class,
                size_gb=vol.size_gb,
                access_modes=access_modes,
                source_pvc_name=vol.name,
                manifest=manifest,
            ))

        return results

    def _build_workload_manifest(
        self,
        name: str,
        kind: str,
        namespace: str,
        replicas: int,
        containers: list[dict],
        spec: dict,
        labels: dict[str, str],
    ) -> dict:
        """Build a complete K8s workload manifest dict."""
        api_version = "apps/v1"
        selector = spec.get("selector", {"matchLabels": labels})
        volumes = spec.get("template", {}).get("spec", {}).get("volumes", [])

        manifest = {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {**labels, "migrated-by": "migration-engine"},
            },
            "spec": {
                "replicas": replicas,
                "selector": selector,
                "template": {
                    "metadata": {"labels": {**labels, "migrated-by": "migration-engine"}},
                    "spec": {
                        "containers": containers,
                        "volumes": volumes,
                    },
                },
            },
        }

        if kind == "StatefulSet":
            manifest["spec"]["serviceName"] = name

        return manifest

    @staticmethod
    def _build_service_manifest(
        name: str,
        namespace: str,
        svc_type: str,
        ports: list[dict],
        selector: dict[str, str],
    ) -> dict:
        """Build a K8s Service manifest dict."""
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {"migrated-by": "migration-engine"},
            },
            "spec": {
                "type": svc_type,
                "selector": selector,
                "ports": ports,
            },
        }

    @staticmethod
    def _build_pvc_manifest(
        name: str,
        namespace: str,
        storage_class: str,
        size_gb: int,
        access_modes: list[str],
    ) -> dict:
        """Build a K8s PVC manifest dict."""
        return {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": {"migrated-by": "migration-engine"},
            },
            "spec": {
                "storageClassName": storage_class,
                "accessModes": access_modes,
                "resources": {
                    "requests": {"storage": f"{size_gb}Gi"},
                },
            },
        }
