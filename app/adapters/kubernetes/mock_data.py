"""Realistic mock data simulating Kubernetes API responses.

Represents a multi-tier production application with:
- 3 Deployments (web frontend, app backend, database)
- 3 Services (ClusterIP for app/db, LoadBalancer for web)
- 2 ConfigMaps (app config, nginx config)
- 3 PersistentVolumeClaims (app data, db data, db logs)
- 1 Namespace
- 1 Secret (db credentials — metadata only)
- 1 HorizontalPodAutoscaler
"""

K8S_MOCK_DATA: dict = {
    "cluster": {
        "name": "prod-cluster-01",
        "version": "1.28.4",
        "provider": "on-premise",
        "region": "dc-primary",
        "node_count": 5,
        "nodes": [
            {
                "name": "node-01",
                "role": "control-plane",
                "status": "Ready",
                "cpu": "8",
                "memory": "32Gi",
                "os_image": "Ubuntu 22.04.3 LTS",
            },
            {
                "name": "node-02",
                "role": "worker",
                "status": "Ready",
                "cpu": "16",
                "memory": "64Gi",
                "os_image": "Ubuntu 22.04.3 LTS",
            },
            {
                "name": "node-03",
                "role": "worker",
                "status": "Ready",
                "cpu": "16",
                "memory": "64Gi",
                "os_image": "Ubuntu 22.04.3 LTS",
            },
            {
                "name": "node-04",
                "role": "worker",
                "status": "Ready",
                "cpu": "16",
                "memory": "64Gi",
                "os_image": "Ubuntu 22.04.3 LTS",
            },
            {
                "name": "node-05",
                "role": "worker",
                "status": "Ready",
                "cpu": "8",
                "memory": "32Gi",
                "os_image": "Ubuntu 22.04.3 LTS",
            },
        ],
    },
    "namespaces": [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": "prod-app",
                "labels": {
                    "env": "production",
                    "team": "platform",
                },
            },
            "status": {"phase": "Active"},
        },
    ],
    "deployments": [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "web-frontend",
                "namespace": "prod-app",
                "labels": {
                    "app": "ecommerce",
                    "tier": "web",
                    "version": "2.1.0",
                },
            },
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": {"app": "ecommerce", "tier": "web"}},
                "template": {
                    "metadata": {
                        "labels": {"app": "ecommerce", "tier": "web"},
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "nginx",
                                "image": "nginx:1.25-alpine",
                                "ports": [{"containerPort": 80}, {"containerPort": 443}],
                                "resources": {
                                    "requests": {"cpu": "250m", "memory": "256Mi"},
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                },
                                "volumeMounts": [
                                    {
                                        "name": "nginx-config",
                                        "mountPath": "/etc/nginx/conf.d",
                                    },
                                ],
                            },
                        ],
                        "volumes": [
                            {
                                "name": "nginx-config",
                                "configMap": {"name": "nginx-config"},
                            },
                        ],
                    },
                },
            },
            "status": {
                "replicas": 3,
                "readyReplicas": 3,
                "availableReplicas": 3,
                "conditions": [
                    {"type": "Available", "status": "True"},
                    {"type": "Progressing", "status": "True"},
                ],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "app-backend",
                "namespace": "prod-app",
                "labels": {
                    "app": "ecommerce",
                    "tier": "app",
                    "version": "3.4.1",
                },
            },
            "spec": {
                "replicas": 2,
                "selector": {"matchLabels": {"app": "ecommerce", "tier": "app"}},
                "template": {
                    "metadata": {
                        "labels": {"app": "ecommerce", "tier": "app"},
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "ecommerce/backend:3.4.1",
                                "ports": [{"containerPort": 8080}],
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                    "limits": {"cpu": "2", "memory": "4Gi"},
                                },
                                "env": [
                                    {
                                        "name": "DB_HOST",
                                        "value": "postgres-db.prod-app.svc.cluster.local",
                                    },
                                    {
                                        "name": "DB_PORT",
                                        "value": "5432",
                                    },
                                    {
                                        "name": "DB_PASSWORD",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "db-credentials",
                                                "key": "password",
                                            },
                                        },
                                    },
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "app-data",
                                        "mountPath": "/var/data",
                                    },
                                    {
                                        "name": "app-config",
                                        "mountPath": "/etc/app",
                                    },
                                ],
                            },
                        ],
                        "volumes": [
                            {
                                "name": "app-data",
                                "persistentVolumeClaim": {"claimName": "app-data-pvc"},
                            },
                            {
                                "name": "app-config",
                                "configMap": {"name": "app-config"},
                            },
                        ],
                    },
                },
            },
            "status": {
                "replicas": 2,
                "readyReplicas": 2,
                "availableReplicas": 2,
                "conditions": [
                    {"type": "Available", "status": "True"},
                ],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": "postgres-db",
                "namespace": "prod-app",
                "labels": {
                    "app": "ecommerce",
                    "tier": "db",
                    "version": "15.4",
                },
            },
            "spec": {
                "replicas": 1,
                "serviceName": "postgres-db",
                "selector": {"matchLabels": {"app": "ecommerce", "tier": "db"}},
                "template": {
                    "metadata": {
                        "labels": {"app": "ecommerce", "tier": "db"},
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "postgres",
                                "image": "postgres:15.4-alpine",
                                "ports": [{"containerPort": 5432}],
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "2Gi"},
                                    "limits": {"cpu": "4", "memory": "8Gi"},
                                },
                                "env": [
                                    {
                                        "name": "POSTGRES_DB",
                                        "value": "ecommerce",
                                    },
                                    {
                                        "name": "POSTGRES_PASSWORD",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "db-credentials",
                                                "key": "password",
                                            },
                                        },
                                    },
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "db-data",
                                        "mountPath": "/var/lib/postgresql/data",
                                    },
                                    {
                                        "name": "db-logs",
                                        "mountPath": "/var/log/postgresql",
                                    },
                                ],
                            },
                        ],
                        "volumes": [
                            {
                                "name": "db-data",
                                "persistentVolumeClaim": {"claimName": "db-data-pvc"},
                            },
                            {
                                "name": "db-logs",
                                "persistentVolumeClaim": {"claimName": "db-logs-pvc"},
                            },
                        ],
                    },
                },
            },
            "status": {
                "replicas": 1,
                "readyReplicas": 1,
            },
        },
    ],
    "services": [
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "web-frontend",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "web"},
            },
            "spec": {
                "type": "LoadBalancer",
                "selector": {"app": "ecommerce", "tier": "web"},
                "ports": [
                    {"name": "http", "port": 80, "targetPort": 80, "protocol": "TCP"},
                    {"name": "https", "port": 443, "targetPort": 443, "protocol": "TCP"},
                ],
            },
            "status": {
                "loadBalancer": {
                    "ingress": [{"ip": "192.168.1.100"}],
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "app-backend",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "app"},
            },
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "ecommerce", "tier": "app"},
                "ports": [
                    {"name": "http", "port": 8080, "targetPort": 8080, "protocol": "TCP"},
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "postgres-db",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "db"},
            },
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "ecommerce", "tier": "db"},
                "ports": [
                    {"name": "postgres", "port": 5432, "targetPort": 5432, "protocol": "TCP"},
                ],
            },
        },
    ],
    "configmaps": [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "nginx-config",
                "namespace": "prod-app",
            },
            "data": {
                "default.conf": (
                    "upstream backend {\n"
                    "    server app-backend:8080;\n"
                    "}\n"
                    "server {\n"
                    "    listen 80;\n"
                    "    location / {\n"
                    "        proxy_pass http://backend;\n"
                    "    }\n"
                    "}\n"
                ),
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "app-config",
                "namespace": "prod-app",
            },
            "data": {
                "application.yaml": (
                    "server:\n"
                    "  port: 8080\n"
                    "database:\n"
                    "  host: postgres-db\n"
                    "  port: 5432\n"
                    "  name: ecommerce\n"
                    "cache:\n"
                    "  enabled: true\n"
                    "  ttl: 300\n"
                ),
            },
        },
    ],
    "pvcs": [
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": "app-data-pvc",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "app"},
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "50Gi"}},
            },
            "status": {
                "phase": "Bound",
                "capacity": {"storage": "50Gi"},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": "db-data-pvc",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "db"},
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "fast-ssd",
                "resources": {"requests": {"storage": "200Gi"}},
            },
            "status": {
                "phase": "Bound",
                "capacity": {"storage": "200Gi"},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": "db-logs-pvc",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "db"},
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "standard",
                "resources": {"requests": {"storage": "20Gi"}},
            },
            "status": {
                "phase": "Bound",
                "capacity": {"storage": "20Gi"},
            },
        },
    ],
    "secrets": [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "db-credentials",
                "namespace": "prod-app",
                "labels": {"app": "ecommerce", "tier": "db"},
            },
            "type": "Opaque",
            "data_keys": ["username", "password"],
        },
    ],
    "hpas": [
        {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": "web-frontend-hpa",
                "namespace": "prod-app",
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": "web-frontend",
                },
                "minReplicas": 2,
                "maxReplicas": 10,
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": 70,
                            },
                        },
                    },
                ],
            },
            "status": {
                "currentReplicas": 3,
                "desiredReplicas": 3,
            },
        },
    ],
}
