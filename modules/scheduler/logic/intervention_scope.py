"""Deterministic grouping for bounded Step 4 intervention scopes."""

from __future__ import annotations

import hashlib

from modules.shared.time_parser import TimeParser


def _minutes(value, *, prefer_end=False):
    return TimeParser.to_minutes(value, default=None, prefer_end=prefer_end)


def _overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def _issue_nodes(cases):
    nodes = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id") or "").strip()
        for issue in case.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            issue_id = str(issue.get("issue_id") or "").strip()
            if not case_id or not issue_id:
                continue
            options = []
            all_options = list(issue.get("options") or [])
            all_options.extend(issue.get("cross_day_options") or [])
            for option in all_options:
                if not isinstance(option, dict):
                    continue
                room = str(option.get("room") or "").strip()
                day = option.get("day")
                start = _minutes(option.get("start"))
                end = _minutes(option.get("end"), prefer_end=True)
                if (
                    not room
                    or day not in range(7)
                    or start is None
                    or end is None
                    or end <= start
                ):
                    continue
                options.append({"room": room, "day": day, "interval": (start, end)})
            nodes.append(
                {
                    "issue_id": issue_id,
                    "case_id": case_id,
                    "day": case.get("day"),
                    "options": options,
                }
            )
    return nodes


def _related(left, right):
    if left["case_id"] == right["case_id"]:
        return "same_case"
    for left_option in left["options"]:
        for right_option in right["options"]:
            if (
                left_option["room"] == right_option["room"]
                and left_option["day"] == right_option["day"]
                and _overlap(left_option["interval"], right_option["interval"])
            ):
                return "shared_room_time"
    return None


def build_related_intervention_groups(cases, *, max_issues=8):
    """Build bounded, deterministic issue groups for a selected day.

    The function does not split a connected component. If a component is
    larger than ``max_issues``, it is returned with ``over_limit=True`` so the
    caller can ask the operator to narrow the scope rather than silently
    cutting a dependency chain.
    """
    if isinstance(max_issues, bool) or not isinstance(max_issues, int) or max_issues < 1:
        raise ValueError("max_issues must be a positive integer")

    nodes = _issue_nodes(cases)
    parent = list(range(len(nodes)))
    reasons: dict[tuple[int, int], set[str]] = {}

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right, reason):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root
        key = tuple(sorted((left, right)))
        reasons.setdefault(key, set()).add(reason)

    for left_index, left in enumerate(nodes):
        for right_index in range(left_index + 1, len(nodes)):
            reason = _related(left, nodes[right_index])
            if reason:
                union(left_index, right_index, reason)

    components = {}
    for index, node in enumerate(nodes):
        components.setdefault(find(index), []).append(node)

    groups = []
    for component in components.values():
        issue_ids = sorted(node["issue_id"] for node in component)
        case_ids = sorted({node["case_id"] for node in component})
        days = sorted(
            {
                node["day"]
                for node in component
                if node.get("day") in range(7)
            }
        )
        component_reasons = set()
        indexes = [nodes.index(node) for node in component]
        for (left, right), values in reasons.items():
            if left in indexes and right in indexes:
                component_reasons.update(values)
        identity = "|".join(issue_ids)
        group_id = "scope-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        groups.append(
            {
                "group_id": group_id,
                "issue_ids": issue_ids,
                "case_ids": case_ids,
                "days": days,
                "size": len(issue_ids),
                "over_limit": len(issue_ids) > max_issues,
                "relation_reasons": sorted(component_reasons),
                "recommended": False,
            }
        )

    groups.sort(key=lambda group: (-group["size"], group["group_id"]))
    if groups:
        groups[0]["recommended"] = True
    return groups
