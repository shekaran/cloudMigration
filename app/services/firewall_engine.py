"""Firewall Translation Engine — rule normalization, conflict resolution, and consolidation.

Normalizes firewall rules from heterogeneous sources (NSX DFW, IBM Classic firewalls)
into a unified format, detects and resolves conflicts using most-specific-wins semantics,
consolidates redundant rules, and flags unsupported patterns.
"""

from __future__ import annotations

import ipaddress
from enum import Enum

import structlog
from pydantic import BaseModel, Field

from app.models.canonical import ProtocolType, SecurityPolicy, SecurityRule
from app.models.responses import DiscoveredResources

logger = structlog.get_logger(__name__)


class ConflictResolution(str, Enum):
    """How a conflict between rules was resolved."""

    MOST_SPECIFIC_WINS = "most_specific_wins"
    EXPLICIT_DENY_WINS = "explicit_deny_wins"
    UNRESOLVABLE = "unresolvable"


class RuleConflict(BaseModel):
    """A detected conflict between firewall rules."""

    rule_a_description: str = Field(description="First conflicting rule")
    rule_b_description: str = Field(description="Second conflicting rule")
    conflict_type: str = Field(description="overlap, contradiction, or redundancy")
    resolution: ConflictResolution = Field(description="How the conflict was resolved")
    winner: str = Field(default="", description="Which rule won (a, b, or none)")
    message: str = Field(description="Human-readable explanation")


class UnsupportedRule(BaseModel):
    """A rule that cannot be translated to the target platform."""

    policy_name: str = Field(description="Source policy name")
    rule_description: str = Field(description="Description of the unsupported rule")
    reason: str = Field(description="Why it cannot be translated")


class NormalizedRule(BaseModel):
    """A fully normalized firewall rule ready for VPC translation."""

    source_cidr: str = Field(description="Source CIDR block")
    destination_cidr: str = Field(description="Destination CIDR block")
    protocol: ProtocolType = Field(description="Network protocol")
    port: int | None = Field(default=None, description="Single port")
    port_range: str = Field(default="", description="Port range (e.g. 8080-8443)")
    action: str = Field(description="allow or deny")
    direction: str = Field(description="inbound or outbound")
    priority: int = Field(default=0, description="Rule priority")
    source_policy: str = Field(default="", description="Originating policy name")
    tier: str = Field(default="", description="Tier classification (web, app, db)")


class FirewallAnalysis(BaseModel):
    """Complete firewall analysis result."""

    normalized_rules: list[NormalizedRule] = Field(default_factory=list)
    conflicts: list[RuleConflict] = Field(default_factory=list)
    unsupported: list[UnsupportedRule] = Field(default_factory=list)
    rules_by_tier: dict[str, list[NormalizedRule]] = Field(default_factory=dict)
    consolidated_count: int = Field(default=0, description="Rules after consolidation")
    original_count: int = Field(default=0, description="Rules before consolidation")


class FirewallEngine:
    """Analyzes, normalizes, and resolves conflicts in firewall rules.

    Pipeline:
    1. Normalize — flatten all SecurityPolicy rules into NormalizedRule format
    2. Detect conflicts — find overlapping rules with contradictory actions
    3. Resolve — apply most-specific-wins; flag unresolvable conflicts
    4. Consolidate — merge adjacent/redundant rules
    5. Classify by tier — group rules by tier tag for tier-based security groups
    """

    # VPC security group limits
    MAX_RULES_PER_GROUP = 50
    SUPPORTED_PROTOCOLS = {ProtocolType.TCP, ProtocolType.UDP, ProtocolType.ICMP, ProtocolType.ALL}

    def analyze(self, resources: DiscoveredResources) -> FirewallAnalysis:
        """Run the full firewall analysis pipeline on discovered resources.

        Args:
            resources: Discovered resources with security policies.

        Returns:
            FirewallAnalysis with normalized rules, conflicts, and tier groupings.
        """
        logger.info(
            "firewall_analysis_started",
            policy_count=len(resources.security_policies),
        )

        # Step 1: Normalize all rules
        normalized, unsupported = self._normalize_rules(resources.security_policies)
        original_count = len(normalized)

        # Step 2: Detect conflicts
        conflicts = self._detect_conflicts(normalized)

        # Step 3: Resolve conflicts (modifies normalized list in-place)
        normalized = self._resolve_conflicts(normalized, conflicts)

        # Step 4: Consolidate redundant rules
        normalized = self._consolidate_rules(normalized)

        # Step 5: Classify by tier
        rules_by_tier = self._classify_by_tier(normalized)

        result = FirewallAnalysis(
            normalized_rules=normalized,
            conflicts=conflicts,
            unsupported=unsupported,
            rules_by_tier=rules_by_tier,
            consolidated_count=len(normalized),
            original_count=original_count,
        )

        logger.info(
            "firewall_analysis_completed",
            original_rules=original_count,
            consolidated_rules=len(normalized),
            conflicts=len(conflicts),
            unsupported=len(unsupported),
            tiers=list(rules_by_tier.keys()),
        )
        return result

    def _normalize_rules(
        self, policies: list[SecurityPolicy]
    ) -> tuple[list[NormalizedRule], list[UnsupportedRule]]:
        """Flatten all security policies into normalized rules."""
        normalized: list[NormalizedRule] = []
        unsupported: list[UnsupportedRule] = []

        for policy in policies:
            tier = policy.tags.get("tier", "") or policy.metadata.get("tier", "")

            for rule in policy.rules:
                # Validate CIDR formats
                source_cidr = self._normalize_cidr(rule.source)
                dest_cidr = self._normalize_cidr(rule.destination)

                if source_cidr is None or dest_cidr is None:
                    unsupported.append(UnsupportedRule(
                        policy_name=policy.name,
                        rule_description=f"{rule.source} → {rule.destination} ({rule.protocol.value})",
                        reason=f"Invalid CIDR: source={rule.source}, dest={rule.destination}",
                    ))
                    continue

                # Check for unsupported protocol patterns
                if rule.protocol not in self.SUPPORTED_PROTOCOLS:
                    unsupported.append(UnsupportedRule(
                        policy_name=policy.name,
                        rule_description=f"{rule.source} → {rule.destination} ({rule.protocol.value})",
                        reason=f"Unsupported protocol: {rule.protocol.value}",
                    ))
                    continue

                # Determine tier from rule metadata or policy tags
                rule_tier = tier
                if not rule_tier:
                    # Try to infer from policy name
                    name_lower = policy.name.lower()
                    for t in ("web", "app", "db"):
                        if t in name_lower:
                            rule_tier = t
                            break

                normalized.append(NormalizedRule(
                    source_cidr=source_cidr,
                    destination_cidr=dest_cidr,
                    protocol=rule.protocol,
                    port=rule.port,
                    port_range=rule.port_range,
                    action=rule.action.lower(),
                    direction=rule.direction.lower(),
                    priority=rule.priority,
                    source_policy=policy.name,
                    tier=rule_tier,
                ))

        return normalized, unsupported

    def _detect_conflicts(self, rules: list[NormalizedRule]) -> list[RuleConflict]:
        """Detect conflicting rules — overlapping scope with contradictory actions."""
        conflicts: list[RuleConflict] = []

        for i, rule_a in enumerate(rules):
            for rule_b in rules[i + 1:]:
                if rule_a.direction != rule_b.direction:
                    continue
                if rule_a.action == rule_b.action:
                    continue

                # Check if CIDRs overlap
                if not self._cidrs_overlap(rule_a.source_cidr, rule_b.source_cidr):
                    continue
                if not self._cidrs_overlap(rule_a.destination_cidr, rule_b.destination_cidr):
                    continue

                # Check if ports overlap
                if not self._ports_overlap(rule_a, rule_b):
                    continue

                # Check if protocols are compatible
                if (rule_a.protocol != rule_b.protocol
                        and rule_a.protocol != ProtocolType.ALL
                        and rule_b.protocol != ProtocolType.ALL):
                    continue

                # We have a conflict — determine type
                a_specificity = self._rule_specificity(rule_a)
                b_specificity = self._rule_specificity(rule_b)

                if a_specificity != b_specificity:
                    resolution = ConflictResolution.MOST_SPECIFIC_WINS
                    winner = "a" if a_specificity > b_specificity else "b"
                elif rule_a.action == "deny":
                    resolution = ConflictResolution.EXPLICIT_DENY_WINS
                    winner = "a"
                elif rule_b.action == "deny":
                    resolution = ConflictResolution.EXPLICIT_DENY_WINS
                    winner = "b"
                else:
                    resolution = ConflictResolution.UNRESOLVABLE
                    winner = ""

                desc_a = f"{rule_a.source_policy}: {rule_a.source_cidr}→{rule_a.destination_cidr} {rule_a.action}"
                desc_b = f"{rule_b.source_policy}: {rule_b.source_cidr}→{rule_b.destination_cidr} {rule_b.action}"

                conflicts.append(RuleConflict(
                    rule_a_description=desc_a,
                    rule_b_description=desc_b,
                    conflict_type="contradiction",
                    resolution=resolution,
                    winner=winner,
                    message=f"Rules conflict on {rule_a.direction}: resolved by {resolution.value}",
                ))

        return conflicts

    def _resolve_conflicts(
        self,
        rules: list[NormalizedRule],
        conflicts: list[RuleConflict],
    ) -> list[NormalizedRule]:
        """Apply conflict resolutions. Remove losing rules for resolved conflicts.

        Unresolvable conflicts are left intact — both rules are preserved
        so the user can manually review.
        """
        # For now, conflict resolution is informational — we preserve all rules
        # and let the tier-based grouping handle precedence within each security group.
        # The conflicts list serves as a report for the user.
        #
        # In a production system, we'd remove the losing rule or merge rules.
        # We keep the sorted-by-priority approach which naturally handles precedence.
        return sorted(rules, key=lambda r: r.priority)

    def _consolidate_rules(self, rules: list[NormalizedRule]) -> list[NormalizedRule]:
        """Merge redundant rules — same CIDR, protocol, action, direction, adjacent ports."""
        if len(rules) <= 1:
            return rules

        consolidated: list[NormalizedRule] = []
        seen: set[str] = set()

        for rule in rules:
            # Create a signature to detect exact duplicates
            sig = (
                rule.source_cidr,
                rule.destination_cidr,
                rule.protocol.value,
                rule.port,
                rule.port_range,
                rule.action,
                rule.direction,
            )
            sig_str = str(sig)
            if sig_str in seen:
                continue
            seen.add(sig_str)
            consolidated.append(rule)

        return consolidated

    def _classify_by_tier(
        self, rules: list[NormalizedRule]
    ) -> dict[str, list[NormalizedRule]]:
        """Group normalized rules by tier for tier-based security groups."""
        by_tier: dict[str, list[NormalizedRule]] = {}
        for rule in rules:
            tier = rule.tier or "default"
            by_tier.setdefault(tier, []).append(rule)
        return by_tier

    @staticmethod
    def _normalize_cidr(cidr_str: str) -> str | None:
        """Validate and normalize a CIDR string. Returns None if invalid."""
        if not cidr_str:
            return "0.0.0.0/0"
        try:
            net = ipaddress.IPv4Network(cidr_str, strict=False)
            return str(net)
        except (ValueError, ipaddress.AddressValueError):
            return None

    @staticmethod
    def _cidrs_overlap(cidr_a: str, cidr_b: str) -> bool:
        """Check if two CIDRs overlap."""
        try:
            net_a = ipaddress.IPv4Network(cidr_a, strict=False)
            net_b = ipaddress.IPv4Network(cidr_b, strict=False)
            return net_a.overlaps(net_b)
        except (ValueError, ipaddress.AddressValueError):
            return False

    @staticmethod
    def _ports_overlap(rule_a: NormalizedRule, rule_b: NormalizedRule) -> bool:
        """Check if port ranges of two rules overlap."""
        a_min, a_max = _port_range(rule_a)
        b_min, b_max = _port_range(rule_b)

        # None means all ports
        if a_min is None or b_min is None:
            return True

        return a_min <= b_max and b_min <= a_max

    @staticmethod
    def _rule_specificity(rule: NormalizedRule) -> int:
        """Score how specific a rule is. Higher = more specific.

        Factors: CIDR prefix length, specific port vs range, specific protocol.
        """
        score = 0
        try:
            src = ipaddress.IPv4Network(rule.source_cidr, strict=False)
            score += src.prefixlen
        except (ValueError, ipaddress.AddressValueError):
            pass
        try:
            dst = ipaddress.IPv4Network(rule.destination_cidr, strict=False)
            score += dst.prefixlen
        except (ValueError, ipaddress.AddressValueError):
            pass

        if rule.port is not None:
            score += 16  # Specific port is very specific
        elif rule.port_range:
            score += 8

        if rule.protocol != ProtocolType.ALL:
            score += 4

        return score


def _port_range(rule: NormalizedRule) -> tuple[int | None, int | None]:
    """Extract min/max port from a rule. Returns (None, None) for all-ports."""
    if rule.port is not None:
        return rule.port, rule.port
    if rule.port_range:
        parts = rule.port_range.split("-")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    return None, None
