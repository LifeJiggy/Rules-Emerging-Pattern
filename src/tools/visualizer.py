"""
Visualizer for rule dependency graphs, evaluation flow, conflict graphs,
and hierarchy displays with ASCII/console output and DOT/JSON export.
"""

import json
import logging
import os
import shutil
import textwrap
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import yaml

from rules_emerging_pattern.models.conflict import ConflictType, ResolutionStrategy, RuleConflict
from rules_emerging_pattern.models.rule import (
    EnforcementLevel,
    Rule,
    RuleContext,
    RulePattern,
    RuleSeverity,
    RuleStatus,
    RuleTier,
    RuleType,
)
from rules_emerging_pattern.models.validation import ValidationResult

logger = logging.getLogger(__name__)


class VisualizationFormat(str, Enum):
    """Output format for visualizations."""
    ASCII = "ascii"
    DOT = "dot"
    JSON = "json"
    YAML = "yaml"
    HTML = "html"


class GraphOrientation(str, Enum):
    """Orientation for graph layouts."""
    TOP_TO_BOTTOM = "TB"
    LEFT_TO_RIGHT = "LR"
    BOTTOM_TO_TOP = "BT"
    RIGHT_TO_LEFT = "RL"


class NodeShape(str, Enum):
    """Shape of nodes in visualizations."""
    BOX = "box"
    ELLIPSE = "ellipse"
    DIAMOND = "diamond"
    ROUNDED = "rounded"
    HEXAGON = "hexagon"


class EdgeStyle(str, Enum):
    """Style of edges in visualizations."""
    SOLID = "solid"
    DASHED = "dashed"
    DOTTED = "dotted"
    BOLD = "bold"


@dataclass
class VisualizerConfig:
    """Configuration for the visualizer."""
    format: VisualizationFormat = VisualizationFormat.ASCII
    orientation: GraphOrientation = GraphOrientation.TOP_TO_BOTTOM
    node_shape: NodeShape = NodeShape.BOX
    edge_style: EdgeStyle = EdgeStyle.SOLID
    max_nodes: int = 100
    max_depth: int = 10
    show_ids: bool = True
    show_tier_colors: bool = True
    show_weights: bool = False
    show_legend: bool = True
    compact_mode: bool = False
    detail_level: int = 2
    wrap_width: int = 40
    indent_size: int = 2
    export_dir: Optional[str] = None
    auto_export: bool = False
    color_scheme: str = "default"
    conflict_highlight: bool = True
    show_perf_annotations: bool = False
    show_unused_rules: bool = False
    show_disabled_rules: bool = False
    group_by_tier: bool = True
    group_by_type: bool = False


@dataclass
class GraphNode:
    """A node in a visualization graph."""
    id: str
    label: str
    node_type: str
    tier: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List["GraphNode"] = field(default_factory=list)
    parent_id: Optional[str] = None


@dataclass
class GraphEdge:
    """An edge in a visualization graph."""
    source_id: str
    target_id: str
    label: Optional[str] = None
    edge_type: str = "default"
    weight: float = 1.0
    style: EdgeStyle = EdgeStyle.SOLID


@dataclass
class VisualizationData:
    """Complete visualization data."""
    title: str
    description: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    config_snapshot: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsciiRenderer:
    """Renders graphs as ASCII art."""

    def __init__(self, config: VisualizerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.AsciiRenderer")

    def render_tree(self, root_nodes: List[GraphNode], edges: List[GraphEdge]) -> str:
        lines = []
        edge_map = defaultdict(list)
        for edge in edges:
            edge_map[edge.source_id].append(edge)
        for i, root in enumerate(root_nodes):
            if i > 0:
                lines.append("")
            lines.append(self._render_node_tree(root, edge_map, "", is_last=(i == len(root_nodes) - 1)))
        return "\n".join(lines)

    def _render_node_tree(self, node: GraphNode, edge_map: Dict, prefix: str, is_last: bool = True) -> str:
        connector = "└── " if is_last else "├── "
        tier_mark = f" [{node.tier}]" if node.tier and self.config.show_tier_colors else ""
        status_mark = f" ({node.status})" if node.status and node.status != "active" else ""
        label = f"{node.label}{tier_mark}{status_mark}"
        if self.config.show_ids:
            label = f"{node.id}: {label}"
        result = f"{prefix}{connector}{label}"
        children = edge_map.get(node.id, [])
        child_nodes = []
        for edge in children:
            child_node = self._find_node(edge.target_id)
            if child_node:
                child_nodes.append(child_node)
        child_count = len(child_nodes)
        for i, child in enumerate(child_nodes):
            child_is_last = (i == child_count - 1)
            child_prefix = prefix + ("    " if is_last else "│   ")
            result += "\n" + self._render_node_tree(child, edge_map, child_prefix, child_is_last)
        return result

    def _find_node(self, node_id: str) -> Optional[GraphNode]:
        return None

    def render_flow(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> str:
        if not nodes:
            return "(empty)"
        lines = []
        layer_map = self._build_layers(nodes, edges)
        max_layer = max(layer_map.keys()) if layer_map else 0
        for layer_idx in range(max_layer + 1):
            layer_nodes = layer_map.get(layer_idx, [])
            if not layer_nodes:
                continue
            node_strs = []
            for node in layer_nodes:
                label = f"[{node.label}]"
                if self.config.show_ids:
                    label = f"[{node.id}] {label}"
                node_strs.append(label)
            node_line = "  ->  ".join(node_strs)
            lines.append(node_line)
            if layer_idx < max_layer:
                connector_line = "    |    " * len(layer_nodes)
                lines.append(connector_line.rstrip())
        return "\n".join(lines)

    def _build_layers(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> Dict[int, List[GraphNode]]:
        node_map = {n.id: n for n in nodes}
        in_degree = defaultdict(int)
        adj = defaultdict(list)
        for edge in edges:
            adj[edge.source_id].append(edge.target_id)
            in_degree[edge.target_id] += 1
        queue = deque()
        for node in nodes:
            if in_degree[node.id] == 0:
                queue.append((node.id, 0))
        layers = defaultdict(list)
        visited = set()
        while queue:
            nid, depth = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = node_map.get(nid)
            if node:
                layers[depth].append(node)
            for child_id in adj[nid]:
                new_depth = depth + 1
                queue.append((child_id, new_depth))
        for node in nodes:
            if node.id not in visited:
                layers[0].append(node)
        return layers

    def render_conflict_graph(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> str:
        lines = []
        lines.append("Conflict Graph")
        lines.append("=" * 50)
        conflict_edges = [e for e in edges if e.edge_type == "conflict"]
        if not conflict_edges:
            lines.append("  No conflicts detected.")
            return "\n".join(lines)
        for edge in conflict_edges:
            src = self._find_node(edge.source_id) or edge.source_id
            tgt = self._find_node(edge.target_id) or edge.target_id
            src_label = src.label if isinstance(src, GraphNode) else src
            tgt_label = tgt.label if isinstance(tgt, GraphNode) else tgt
            lines.append(f"  {src_label} <-> {tgt_label}")
            if edge.label:
                lines.append(f"    {edge.label}")
        lines.append("")
        lines.append(f"Total conflicts: {len(conflict_edges)}")
        return "\n".join(lines)

    def render_hierarchy(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> str:
        lines = []
        lines.append("Rule Hierarchy")
        lines.append("=" * 50)
        tier_order = ["safety", "operational", "preference"]
        grouped = defaultdict(list)
        for node in nodes:
            tier = node.tier or "unknown"
            grouped[tier].append(node)
        for tier in tier_order:
            tier_nodes = grouped.get(tier, [])
            if not tier_nodes:
                continue
            lines.append(f"\n[{tier.upper()}]")
            for node in tier_nodes:
                label = node.label
                if self.config.show_ids:
                    label = f"  {node.id}: {label}"
                else:
                    label = f"  - {label}"
                if node.status:
                    label += f" ({node.status})"
                lines.append(label)
                child_edges = [e for e in edges if e.source_id == node.id]
                if child_edges:
                    for ce in child_edges:
                        child_node = self._find_node(ce.target_id)
                        if child_node:
                            lines.append(f"      -> {child_node.label}")
        lines.append("")
        return "\n".join(lines)


class DotRenderer:
    """Renders graphs in DOT format for Graphviz."""

    def __init__(self, config: VisualizerConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.DotRenderer")

    def render(self, data: VisualizationData) -> str:
        lines = []
        graph_type = "digraph"
        lines.append(f"{graph_type} \"{data.title}\" {{")
        lines.append(f"  rankdir={self.config.orientation.value};")
        lines.append(f"  node [shape={self.config.node_shape.value}];")
        lines.append(f"  edge [style={self.config.edge_style.value}];")
        lines.append("")
        lines.append("  // Nodes")
        for node in data.nodes:
            attrs = []
            attrs.append(f"label=\"{self._escape(node.label)}\"")
            if node.tier:
                color = self._tier_color(node.tier)
                attrs.append(f"color=\"{color}\"")
                attrs.append(f"fontcolor=\"{color}\"")
            if node.status:
                if node.status == "inactive" or node.status == "deprecated":
                    attrs.append("style=dashed")
            node_id = self._escape_id(node.id)
            attrs_str = ", ".join(attrs)
            lines.append(f"  {node_id} [{attrs_str}];")
        lines.append("")
        lines.append("  // Edges")
        for edge in data.edges:
            src = self._escape_id(edge.source_id)
            tgt = self._escape_id(edge.target_id)
            attrs = []
            if edge.label:
                attrs.append(f"label=\"{self._escape(edge.label)}\"")
            if edge.edge_type == "conflict":
                attrs.append("color=\"red\"")
                attrs.append("style=dashed")
            elif edge.edge_type == "dependency":
                attrs.append("color=\"blue\"")
            if edge.weight != 1.0:
                attrs.append(f"weight=\"{edge.weight}\"")
            if attrs:
                attrs_str = " [" + ", ".join(attrs) + "]"
            else:
                attrs_str = ""
            lines.append(f"  {src} -> {tgt}{attrs_str};")
        lines.append("")
        lines.append("  // Legend")
        if self.config.show_legend:
            lines.append("  subgraph cluster_legend {")
            lines.append("    label=\"Legend\";")
            lines.append("    style=dashed;")
            lines.append("    legend_safety [label=\"Safety\", color=\"red\", fontcolor=\"red\"];")
            lines.append("    legend_operational [label=\"Operational\", color=\"blue\", fontcolor=\"blue\"];")
            lines.append("    legend_preference [label=\"Preference\", color=\"green\", fontcolor=\"green\"];")
            lines.append("  }")
        lines.append("}")
        return "\n".join(lines)

    def _escape(self, text: str) -> str:
        return text.replace("\"", "\\\"").replace("\\", "\\\\").replace("\n", "\\n")

    def _escape_id(self, node_id: str) -> str:
        if node_id.startswith("_"):
            return f"n{uuid.uuid4().hex[:8]}"
        return node_id.replace("-", "_").replace(".", "_").replace(" ", "_")

    def _tier_color(self, tier: str) -> str:
        tier_colors = {
            "safety": "red",
            "operational": "blue",
            "preference": "green",
            "unknown": "gray",
        }
        return tier_colors.get(tier, "black")


class Visualizer:
    """
    Visualization tool for rule dependency graphs, evaluation flow,
    conflict graphs, and hierarchy displays.

    Supports ASCII/console output, DOT (Graphviz), JSON, YAML, and HTML formats.
    """

    def __init__(self, config: Optional[VisualizerConfig] = None):
        self.config = config or VisualizerConfig()
        self._ascii_renderer = AsciiRenderer(self.config)
        self._dot_renderer = DotRenderer(self.config)
        self._graph_data: Optional[VisualizationData] = None
        self.logger = logging.getLogger(f"{__name__}.Visualizer")

    def update_config(self, config_updates: Dict[str, Any]) -> None:
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self._ascii_renderer = AsciiRenderer(self.config)
        self._dot_renderer = DotRenderer(self.config)
        self.logger.info("Visualizer config updated with %d changes", len(config_updates))

    def build_dependency_graph(self, rules: List[Rule]) -> VisualizationData:
        nodes = []
        edges = []
        node_map = {}
        for rule in rules:
            node = GraphNode(
                id=rule.id,
                label=rule.name,
                node_type="rule",
                tier=rule.tier.value if rule.tier else None,
                severity=rule.severity.value if rule.severity else None,
                status=rule.status.value if rule.status else None,
                metadata={
                    "description": rule.description[:100],
                    "type": rule.rule_type.value if rule.rule_type else None,
                    "priority": rule.priority,
                },
            )
            node_map[rule.id] = node
            nodes.append(node)
        for rule in rules:
            deps = rule.conditions.get("depends_on", [])
            if isinstance(deps, list):
                for dep_id in deps:
                    if dep_id in node_map:
                        edges.append(GraphEdge(
                            source_id=rule.id,
                            target_id=dep_id,
                            label="depends_on",
                            edge_type="dependency",
                            style=EdgeStyle.DASHED,
                        ))
            if rule.tier == RuleTier.PREFERENCE:
                pass
        for i, rule_a in enumerate(rules):
            for rule_b in rules[i + 1:]:
                shared_tags = set(rule_a.tags) & set(rule_b.tags)
                if shared_tags:
                    edges.append(GraphEdge(
                        source_id=rule_a.id,
                        target_id=rule_b.id,
                        label=f"shared:{','.join(list(shared_tags)[:3])}",
                        edge_type="relationship",
                        weight=0.5,
                        style=EdgeStyle.DOTTED,
                    ))
        title = f"Rule Dependency Graph ({len(rules)} rules)"
        data = VisualizationData(
            title=title,
            description=f"Dependency graph for {len(rules)} rules with {len(edges)} relationships",
            nodes=nodes,
            edges=edges,
            config_snapshot=self._config_to_dict(),
            metadata={"rule_count": len(rules), "edge_count": len(edges)},
        )
        self._graph_data = data
        return data

    def build_evaluation_flow(self, rules: List[Rule], matched_rule_ids: Optional[List[str]] = None) -> VisualizationData:
        nodes = []
        edges = []
        matched_set = set(matched_rule_ids or [])
        eval_start = GraphNode(
            id="_evaluation_start",
            label="Evaluation Start",
            node_type="start",
        )
        nodes.append(eval_start)
        tier_order = [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]
        tier_nodes = defaultdict(list)
        for rule in rules:
            node = GraphNode(
                id=f"eval_{rule.id}",
                label=rule.name,
                node_type="evaluation",
                tier=rule.tier.value if rule.tier else None,
                status="matched" if rule.id in matched_set else "checked",
                metadata={
                    "matched": rule.id in matched_set,
                    "priority": rule.priority,
                },
            )
            tier_nodes[rule.tier or RuleTier.OPERATIONAL].append(node)
            nodes.append(node)
        prev_tier_node = eval_start
        for tier in tier_order:
            tier_rules = sorted(tier_nodes[tier], key=lambda n: n.metadata.get("priority", 100))
            if not tier_rules:
                continue
            tier_start = GraphNode(
                id=f"_tier_{tier.value}_start",
                label=f"Tier: {tier.value}",
                node_type="tier_boundary",
                tier=tier.value,
            )
            nodes.append(tier_start)
            edges.append(GraphEdge(
                source_id=prev_tier_node.id,
                target_id=tier_start.id,
                label="next tier",
                edge_type="flow",
            ))
            for i, rule_node in enumerate(tier_rules):
                if i == 0:
                    edges.append(GraphEdge(
                        source_id=tier_start.id,
                        target_id=rule_node.id,
                        label="",
                        edge_type="flow",
                    ))
                else:
                    edges.append(GraphEdge(
                        source_id=tier_rules[i - 1].id,
                        target_id=rule_node.id,
                        label="",
                        edge_type="flow",
                    ))
            prev_tier_node = tier_rules[-1] if tier_rules else tier_start
        eval_end = GraphNode(
            id="_evaluation_end",
            label="Evaluation End",
            node_type="end",
        )
        nodes.append(eval_end)
        edges.append(GraphEdge(
            source_id=prev_tier_node.id,
            target_id=eval_end.id,
            label="",
            edge_type="flow",
        ))
        if matched_rule_ids:
            for rule_id in matched_rule_ids:
                node_id = f"eval_{rule_id}"
                node = next((n for n in nodes if n.id == node_id), None)
                if node:
                    node.metadata["matched"] = True
        data = VisualizationData(
            title="Evaluation Flow",
            description=f"Evaluation flow for {len(rules)} rules across {len(tier_order)} tiers",
            nodes=nodes,
            edges=edges,
            config_snapshot=self._config_to_dict(),
            metadata={"matched_count": len(matched_set)},
        )
        self._graph_data = data
        return data

    def build_conflict_graph(self, rules: List[Rule], conflicts: Optional[List[RuleConflict]] = None) -> VisualizationData:
        nodes = []
        edges = []
        node_map = {}
        for rule in rules:
            node = GraphNode(
                id=rule.id,
                label=rule.name,
                node_type="rule",
                tier=rule.tier.value if rule.tier else None,
                severity=rule.severity.value if rule.severity else None,
                status=rule.status.value if rule.status else None,
            )
            node_map[rule.id] = node
            nodes.append(node)
        if conflicts:
            for conflict in conflicts:
                edge_label = conflict.conflict_type.value
                edges.append(GraphEdge(
                    source_id=conflict.rule_1.id,
                    target_id=conflict.rule_2.id,
                    label=edge_label,
                    edge_type="conflict",
                    style=EdgeStyle.DASHED,
                ))
                for extra_rule in conflict.additional_rules:
                    edges.append(GraphEdge(
                        source_id=conflict.rule_1.id,
                        target_id=extra_rule.id,
                        label=edge_label,
                        edge_type="conflict",
                        style=EdgeStyle.DASHED,
                    ))
        data = VisualizationData(
            title="Conflict Graph",
            description=f"Conflict graph for {len(rules)} rules with {len(edges)} conflict edges",
            nodes=nodes,
            edges=edges,
            config_snapshot=self._config_to_dict(),
            metadata={"conflict_count": len(conflicts or []), "edge_count": len(edges)},
        )
        self._graph_data = data
        return data

    def build_hierarchy(self, rules: List[Rule]) -> VisualizationData:
        nodes = []
        edges = []
        tier_order = [RuleTier.SAFETY, RuleTier.OPERATIONAL, RuleTier.PREFERENCE]
        for tier in tier_order:
            tier_node = GraphNode(
                id=f"_hierarchy_{tier.value}",
                label=f"Tier: {tier.value}",
                node_type="tier_header",
                tier=tier.value,
            )
            nodes.append(tier_node)
        type_groups = defaultdict(list)
        for rule in rules:
            rtype = rule.rule_type or RuleType.CUSTOM
            type_groups[(rule.tier or RuleTier.OPERATIONAL, rtype)].append(rule)
        for tier in tier_order:
            tier_node_id = f"_hierarchy_{tier.value}"
            for rtype in RuleType:
                group_rules = type_groups.get((tier, rtype), [])
                if not group_rules:
                    continue
                type_node = GraphNode(
                    id=f"_hierarchy_{tier.value}_{rtype.value}",
                    label=f"{rtype.value}",
                    node_type="type_header",
                    tier=tier.value,
                )
                nodes.append(type_node)
                edges.append(GraphEdge(
                    source_id=tier_node_id,
                    target_id=type_node.id,
                    label="",
                    edge_type="hierarchy",
                ))
                for rule in group_rules:
                    rule_node = GraphNode(
                        id=rule.id,
                        label=rule.name,
                        node_type="rule",
                        tier=tier.value if rule.tier else None,
                        severity=rule.severity.value if rule.severity else None,
                        status=rule.status.value if rule.status else None,
                        metadata={"type": rtype.value},
                    )
                    nodes.append(rule_node)
                    edges.append(GraphEdge(
                        source_id=type_node.id,
                        target_id=rule.id,
                        label="",
                        edge_type="hierarchy",
                    ))
        data = VisualizationData(
            title="Rule Hierarchy",
            description=f"Hierarchical view of {len(rules)} rules by tier and type",
            nodes=nodes,
            edges=edges,
            config_snapshot=self._config_to_dict(),
            metadata={"rule_count": len(rules), "node_count": len(nodes), "edge_count": len(edges)},
        )
        self._graph_data = data
        return data

    def render(self, data: Optional[VisualizationData] = None, format: Optional[VisualizationFormat] = None) -> str:
        viz_data = data or self._graph_data
        if not viz_data:
            return "No visualization data available"
        fmt = format or self.config.format
        if fmt == VisualizationFormat.ASCII:
            return self._render_ascii(viz_data)
        elif fmt == VisualizationFormat.DOT:
            return self._render_dot(viz_data)
        elif fmt == VisualizationFormat.JSON:
            return self._render_json(viz_data)
        elif fmt == VisualizationFormat.YAML:
            return self._render_yaml(viz_data)
        elif fmt == VisualizationFormat.HTML:
            return self._render_html(viz_data)
        return self._render_ascii(viz_data)

    def _render_ascii(self, data: VisualizationData) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(data.title)
        lines.append("=" * 60)
        lines.append("")
        if "Dependency" in data.title or "Hierarchy" in data.title:
            root_nodes = [n for n in data.nodes if n.node_type in ("start", "tier_header") or n.parent_id is None]
            lines.append(self._ascii_renderer.render_tree(root_nodes, data.edges))
        elif "Flow" in data.title:
            lines.append(self._ascii_renderer.render_flow(data.nodes, data.edges))
        elif "Conflict" in data.title:
            lines.append(self._ascii_renderer.render_conflict_graph(data.nodes, data.edges))
        else:
            lines.append(self._ascii_renderer.render_hierarchy(data.nodes, data.edges))
        lines.append("")
        if self.config.show_legend:
            lines.append("Legend:")
            lines.append("  [safety] - Safety tier rules")
            lines.append("  [operational] - Operational tier rules")
            lines.append("  [preference] - Preference tier rules")
            lines.append("  (inactive) - Inactive rule")
            lines.append("  (deprecated) - Deprecated rule")
            lines.append("  -> - Dependency/flow")
            lines.append("  <-> - Conflict")
            lines.append("  ... - Relationship")
        lines.append("")
        lines.append(f"Nodes: {len(data.nodes)}, Edges: {len(data.edges)}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _render_dot(self, data: VisualizationData) -> str:
        return self._dot_renderer.render(data)

    def _render_json(self, data: VisualizationData) -> str:
        payload = {
            "title": data.title,
            "description": data.description,
            "created_at": data.created_at.isoformat(),
            "metadata": data.metadata,
            "config": data.config_snapshot,
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.node_type,
                    "tier": n.tier,
                    "severity": n.severity,
                    "status": n.status,
                    "metadata": n.metadata,
                }
                for n in data.nodes
            ],
            "edges": [
                {
                    "source": e.source_id,
                    "target": e.target_id,
                    "label": e.label,
                    "type": e.edge_type,
                    "weight": e.weight,
                }
                for e in data.edges
            ],
        }
        return json.dumps(payload, indent=2, default=str)

    def _render_yaml(self, data: VisualizationData) -> str:
        payload = {
            "title": data.title,
            "description": data.description,
            "node_count": len(data.nodes),
            "edge_count": len(data.edges),
            "metadata": dict(data.metadata),
        }
        return yaml.dump(payload, default_flow_style=False, sort_keys=False)

    def _render_html(self, data: VisualizationData) -> str:
        lines = []
        lines.append("<!DOCTYPE html>")
        lines.append("<html>")
        lines.append("<head>")
        lines.append(f"  <title>{data.title}</title>")
        lines.append("  <style>")
        lines.append("    body { font-family: monospace; margin: 20px; }")
        lines.append("    .node { padding: 5px; margin: 2px; border: 1px solid #ccc; }")
        lines.append("    .safety { border-color: red; color: red; }")
        lines.append("    .operational { border-color: blue; color: blue; }")
        lines.append("    .preference { border-color: green; color: green; }")
        lines.append("    .matched { background: #d4edda; }")
        lines.append("    .conflict { border-color: red; border-style: dashed; }")
        lines.append("  </style>")
        lines.append("</head>")
        lines.append("<body>")
        lines.append(f"  <h1>{data.title}</h1>")
        lines.append(f"  <p>{data.description}</p>")
        lines.append("  <h2>Nodes</h2>")
        lines.append("  <ul>")
        for node in data.nodes:
            css_class = node.tier or ""
            if node.metadata.get("matched"):
                css_class += " matched"
            lines.append(f"    <li class=\"node {css_class}\">{node.label} ({node.id}) [{node.tier or 'unknown'}]</li>")
        lines.append("  </ul>")
        lines.append("  <h2>Edges</h2>")
        lines.append("  <ul>")
        for edge in data.edges:
            label = f" - {edge.label}" if edge.label else ""
            edge_class = "conflict" if edge.edge_type == "conflict" else ""
            lines.append(f"    <li class=\"{edge_class}\">{edge.source_id} -> {edge.target_id}{label}</li>")
        lines.append("  </ul>")
        lines.append("</body>")
        lines.append("</html>")
        return "\n".join(lines)

    def export(self, data: Optional[VisualizationData] = None, filepath: Optional[str] = None, format: Optional[VisualizationFormat] = None) -> str:
        viz_data = data or self._graph_data
        if not viz_data:
            raise RuntimeError("No visualization data to export")
        fmt = format or self.config.format
        content = self.render(viz_data, fmt)
        if filepath:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.logger.info("Visualization exported to %s", filepath)
            return str(path)
        if self.config.export_dir:
            ext_map = {
                VisualizationFormat.ASCII: ".txt",
                VisualizationFormat.DOT: ".dot",
                VisualizationFormat.JSON: ".json",
                VisualizationFormat.YAML: ".yaml",
                VisualizationFormat.HTML: ".html",
            }
            ext = ext_map.get(fmt, ".txt")
            path = Path(self.config.export_dir) / f"viz_{viz_data.title.replace(' ', '_')}_{uuid.uuid4().hex[:8]}{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.logger.info("Visualization exported to %s", path)
            return str(path)
        return content

    def print_ascii(self, data: Optional[VisualizationData] = None) -> None:
        output = self.render(data, VisualizationFormat.ASCII)
        print(output)

    def _config_to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.config.format.value,
            "orientation": self.config.orientation.value,
            "node_shape": self.config.node_shape.value,
            "max_nodes": self.config.max_nodes,
            "show_ids": self.config.show_ids,
            "show_tier_colors": self.config.show_tier_colors,
            "show_legend": self.config.show_legend,
            "compact_mode": self.config.compact_mode,
            "group_by_tier": self.config.group_by_tier,
        }

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "format": {
                "type": "string",
                "enum": [e.value for e in VisualizationFormat],
                "default": "ascii",
            },
            "orientation": {
                "type": "string",
                "enum": [e.value for e in GraphOrientation],
                "default": "TB",
            },
            "node_shape": {
                "type": "string",
                "enum": [e.value for e in NodeShape],
                "default": "box",
            },
            "max_nodes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 100,
            },
            "show_ids": {"type": "boolean", "default": True},
            "show_tier_colors": {"type": "boolean", "default": True},
            "show_legend": {"type": "boolean", "default": True},
            "compact_mode": {"type": "boolean", "default": False},
            "group_by_tier": {"type": "boolean", "default": True},
        }
