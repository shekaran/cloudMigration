"""Dependency graph engine — builds directed graphs, topological sort, cycle detection, Graphviz export."""

from collections import defaultdict, deque
from uuid import UUID

import structlog

from app.models.common import DependencyType, ResourceDependency
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class CyclicDependencyError(Exception):
    """Raised when the dependency graph contains a cycle."""

    def __init__(self, cycle: list[UUID]) -> None:
        self.cycle = cycle
        names = " → ".join(str(uid) for uid in cycle)
        super().__init__(f"Cyclic dependency detected: {names}")


class DependencyGraph:
    """Directed acyclic graph of resource dependencies.

    Nodes are resource UUIDs; edges represent dependencies (source depends on target).
    """

    def __init__(self) -> None:
        self._adjacency: dict[UUID, set[UUID]] = defaultdict(set)
        self._reverse: dict[UUID, set[UUID]] = defaultdict(set)
        self._nodes: set[UUID] = set()
        self._node_labels: dict[UUID, str] = {}
        self._node_types: dict[UUID, str] = {}
        self._edge_types: dict[tuple[UUID, UUID], DependencyType] = {}

    @property
    def nodes(self) -> set[UUID]:
        return self._nodes.copy()

    @property
    def edge_count(self) -> int:
        return sum(len(targets) for targets in self._adjacency.values())

    def add_node(self, node_id: UUID, label: str = "", node_type: str = "") -> None:
        """Register a node in the graph."""
        self._nodes.add(node_id)
        if label:
            self._node_labels[node_id] = label
        if node_type:
            self._node_types[node_id] = node_type

    def add_edge(
        self,
        source: UUID,
        target: UUID,
        dep_type: DependencyType = DependencyType.COMPUTE,
    ) -> None:
        """Add a directed edge: source depends on target."""
        self._nodes.add(source)
        self._nodes.add(target)
        self._adjacency[source].add(target)
        self._reverse[target].add(source)
        self._edge_types[(source, target)] = dep_type

    def dependencies_of(self, node_id: UUID) -> set[UUID]:
        """Return direct dependencies of a node (nodes it depends on)."""
        return self._adjacency.get(node_id, set()).copy()

    def dependents_of(self, node_id: UUID) -> set[UUID]:
        """Return direct dependents of a node (nodes that depend on it)."""
        return self._reverse.get(node_id, set()).copy()

    def detect_cycles(self) -> list[list[UUID]]:
        """Detect all cycles in the graph using DFS.

        Returns a list of cycles (each cycle is a list of UUIDs).
        Returns empty list if the graph is acyclic.
        """
        visited: set[UUID] = set()
        rec_stack: set[UUID] = set()
        path: list[UUID] = []
        cycles: list[list[UUID]] = []

        def _dfs(node: UUID) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._adjacency.get(node, set()):
                if neighbor not in visited:
                    _dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle — extract it from path
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

            path.pop()
            rec_stack.discard(node)

        for node in self._nodes:
            if node not in visited:
                _dfs(node)

        return cycles

    def topological_sort(self) -> list[UUID]:
        """Return nodes in topological order (Kahn's algorithm).

        Dependencies come before the nodes that depend on them.
        Raises CyclicDependencyError if a cycle exists.
        """
        in_degree: dict[UUID, int] = {node: 0 for node in self._nodes}
        for source, targets in self._adjacency.items():
            for target in targets:
                in_degree.setdefault(target, 0)
                # source depends on target, so target must come first
                # We need in-degree in the "execution" direction:
                # if A depends on B, then A has an incoming edge from B in execution order
                pass

        # Recompute: in execution order, an edge from target→source means
        # "target must execute before source". Use reverse adjacency for in-degree.
        exec_in_degree: dict[UUID, int] = {node: 0 for node in self._nodes}
        for source, targets in self._adjacency.items():
            # source depends on targets → targets must come first → source has in-degree from each target
            exec_in_degree.setdefault(source, 0)
            exec_in_degree[source] += len(targets)

        queue: deque[UUID] = deque()
        for node, degree in exec_in_degree.items():
            if degree == 0:
                queue.append(node)

        result: list[UUID] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            # This node is "executed" — reduce in-degree of its dependents
            for dependent in self._reverse.get(node, set()):
                exec_in_degree[dependent] -= 1
                if exec_in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._nodes):
            cycles = self.detect_cycles()
            raise CyclicDependencyError(cycles[0] if cycles else list(self._nodes))

        return result

    def parallel_stages(self) -> list[list[UUID]]:
        """Group nodes into parallel execution stages.

        Each stage contains nodes that can execute concurrently.
        All dependencies of a node in stage N are in stages < N.
        """
        order = self.topological_sort()  # raises if cyclic
        node_stage: dict[UUID, int] = {}

        for node in order:
            deps = self._adjacency.get(node, set())
            if not deps:
                node_stage[node] = 0
            else:
                node_stage[node] = max(node_stage.get(d, 0) for d in deps) + 1

        # Group by stage
        stages: dict[int, list[UUID]] = defaultdict(list)
        for node, stage in node_stage.items():
            stages[stage].append(node)

        return [stages[i] for i in sorted(stages.keys())]

    def to_dict(self) -> dict:
        """Export graph as JSON-serializable dict."""
        nodes = []
        for node_id in self._nodes:
            nodes.append({
                "id": str(node_id),
                "label": self._node_labels.get(node_id, str(node_id)),
                "type": self._node_types.get(node_id, "unknown"),
            })

        edges = []
        for source, targets in self._adjacency.items():
            for target in targets:
                edges.append({
                    "source": str(source),
                    "target": str(target),
                    "type": self._edge_types.get(
                        (source, target), DependencyType.COMPUTE
                    ).value,
                })

        return {"nodes": nodes, "edges": edges}

    def to_dot(self) -> str:
        """Export graph as Graphviz DOT format for visualization."""
        type_colors = {
            "compute": "#4A90D9",
            "network": "#7CB342",
            "security_policy": "#FF7043",
            "storage": "#AB47BC",
        }
        type_shapes = {
            "compute": "box",
            "network": "ellipse",
            "security_policy": "diamond",
            "storage": "cylinder",
        }
        edge_styles = {
            DependencyType.NETWORK: "solid",
            DependencyType.STORAGE: "dashed",
            DependencyType.COMPUTE: "bold",
            DependencyType.SECURITY: "dotted",
            DependencyType.RUNTIME: "solid",
        }

        lines = [
            "digraph MigrationDependencies {",
            '  rankdir=TB;',
            '  node [fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=8];',
            "",
        ]

        for node_id in self._nodes:
            label = self._node_labels.get(node_id, str(node_id)[:8])
            ntype = self._node_types.get(node_id, "unknown")
            color = type_colors.get(ntype, "#888888")
            shape = type_shapes.get(ntype, "box")
            safe_id = str(node_id).replace("-", "_")
            lines.append(
                f'  "{safe_id}" [label="{label}\\n({ntype})", '
                f'shape={shape}, style=filled, fillcolor="{color}", fontcolor=white];'
            )

        lines.append("")

        for source, targets in self._adjacency.items():
            for target in targets:
                dep_type = self._edge_types.get(
                    (source, target), DependencyType.COMPUTE
                )
                style = edge_styles.get(dep_type, "solid")
                src = str(source).replace("-", "_")
                tgt = str(target).replace("-", "_")
                lines.append(
                    f'  "{src}" -> "{tgt}" [label="{dep_type.value}", style={style}];'
                )

        lines.append("}")
        return "\n".join(lines)


def build_graph(resources: DiscoveredResources) -> DependencyGraph:
    """Build a DependencyGraph from discovered resources.

    Registers all resources as nodes and all ResourceDependency entries as edges.
    """
    graph = DependencyGraph()

    # Register all resources as nodes
    for vm in resources.compute:
        graph.add_node(vm.id, label=vm.name, node_type="compute")
    for net in resources.networks:
        graph.add_node(net.id, label=net.name, node_type="network")
    for sp in resources.security_policies:
        graph.add_node(sp.id, label=sp.name, node_type="security_policy")
    for vol in resources.storage:
        graph.add_node(vol.id, label=vol.name, node_type="storage")

    # Register all dependency edges
    all_resources = (
        list(resources.compute)
        + list(resources.networks)
        + list(resources.security_policies)
        + list(resources.storage)
    )
    for resource in all_resources:
        for dep in resource.dependencies:
            if dep.target_id in graph.nodes:
                graph.add_edge(dep.source_id, dep.target_id, dep.dependency_type)

    logger.info(
        "dependency_graph_built",
        nodes=len(graph.nodes),
        edges=graph.edge_count,
    )
    return graph
