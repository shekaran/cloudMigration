"""IBM Cloud Kubernetes target resource models.

Supports both IBM Kubernetes Service (IKS) and Red Hat OpenShift on IBM Cloud
as configurable target platforms.
"""

from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class K8sTargetPlatform(str, Enum):
    """Supported Kubernetes target platforms on IBM Cloud."""

    IKS = "iks"
    OPENSHIFT = "openshift"


class K8sTargetCluster(BaseModel):
    """Target Kubernetes cluster configuration."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="Cluster name")
    platform: K8sTargetPlatform = Field(description="IKS or OpenShift")
    region: str = Field(default="us-south", description="IBM Cloud region")
    version: str = Field(description="Target K8s/OpenShift version")
    worker_pool_flavor: str = Field(
        default="bx2.4x16", description="Worker node machine type"
    )
    worker_count: int = Field(default=3, description="Number of worker nodes")
    vpc_id: str = Field(default="", description="VPC to deploy cluster into")


class K8sTargetNamespace(BaseModel):
    """Target namespace in the K8s cluster."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="Namespace name")
    cluster_id: UUID = Field(description="Target cluster ID")
    labels: dict[str, str] = Field(default_factory=dict)
    source_namespace: str = Field(default="", description="Original namespace name")


class K8sTargetWorkload(BaseModel):
    """A translated K8s workload (Deployment/StatefulSet) for the target cluster."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="Workload name")
    kind: str = Field(description="Deployment or StatefulSet")
    namespace: str = Field(description="Target namespace")
    replicas: int = Field(default=1)
    containers: list[dict] = Field(default_factory=list, description="Container specs")
    volumes: list[dict] = Field(default_factory=list, description="Volume specs")
    labels: dict[str, str] = Field(default_factory=dict)
    source_workload_name: str = Field(default="", description="Original workload name")
    manifest: dict = Field(default_factory=dict, description="Full K8s YAML manifest as dict")


class K8sTargetService(BaseModel):
    """A translated K8s Service for the target cluster."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="Service name")
    namespace: str = Field(description="Target namespace")
    service_type: str = Field(default="ClusterIP", description="ClusterIP, LoadBalancer, NodePort")
    ports: list[dict] = Field(default_factory=list)
    selector: dict[str, str] = Field(default_factory=dict)
    source_service_name: str = Field(default="")
    manifest: dict = Field(default_factory=dict, description="Full K8s YAML manifest as dict")


class K8sTargetStorage(BaseModel):
    """A translated PVC for the target cluster."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(description="PVC name")
    namespace: str = Field(description="Target namespace")
    storage_class: str = Field(default="ibmc-vpc-block-5iops-tier")
    size_gb: int = Field(description="Storage size in GB")
    access_modes: list[str] = Field(default_factory=lambda: ["ReadWriteOnce"])
    source_pvc_name: str = Field(default="")
    manifest: dict = Field(default_factory=dict, description="Full K8s YAML manifest as dict")


class K8sTranslationResult(BaseModel):
    """Complete translation output for Kubernetes migration."""

    cluster: K8sTargetCluster
    namespaces: list[K8sTargetNamespace] = Field(default_factory=list)
    workloads: list[K8sTargetWorkload] = Field(default_factory=list)
    services: list[K8sTargetService] = Field(default_factory=list)
    storage: list[K8sTargetStorage] = Field(default_factory=list)

    @property
    def resource_count(self) -> int:
        return (
            1  # cluster
            + len(self.namespaces)
            + len(self.workloads)
            + len(self.services)
            + len(self.storage)
        )
