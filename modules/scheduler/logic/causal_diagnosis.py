"""Deterministic aggregation of a bounded Step 4 conflict neighborhood."""

from __future__ import annotations

from collections import Counter


def build_local_causal_diagnosis(cases, *, piano_proposals=None):
    traces = [
        trace
        for case in cases or []
        for issue in case.get("issues") or []
        for trace in issue.get("rejection_trace") or []
        if isinstance(trace, dict)
    ]
    room_counts = Counter(
        str(trace.get("room"))
        for trace in traces
        if trace.get("room")
        and trace.get("code") in {"locked_lecture", "room_occupied", "room_incompatible"}
    )
    locked = sum(
        trace.get("blocker_kind") == "locked_lecture" for trace in traces
    )
    movable = sum(bool(trace.get("movable")) for trace in traces)
    instructor = sum(
        trace.get("code") == "instructor_conflict" for trace in traces
    )
    incompatible = sum(
        trace.get("code") == "room_incompatible" for trace in traces
    )
    room_blockers = sum(
        trace.get("code") in {"locked_lecture", "room_occupied"}
        for trace in traces
    )
    proposals = sorted(
        [
            {
                "proposal_id": proposal.get("id"),
                "instructor": proposal.get("instructor"),
                "target_room": proposal.get("target_room"),
                "target_day": proposal.get("target_day"),
                "target_start": proposal.get("target_start"),
                "target_end": proposal.get("target_end"),
                "gain": int(proposal.get("gain") or 0),
                "moves": [
                    {
                        "assignment_id": move.get("assignment_id"),
                        "from_room": move.get("from_room"),
                        "from_day": move.get("from_day"),
                        "from_start": move.get("from_start"),
                        "from_end": move.get("from_end"),
                        "to_room": move.get("to_room"),
                        "to_day": move.get("to_day"),
                        "to_start": move.get("to_start"),
                        "to_end": move.get("to_end"),
                    }
                    for move in proposal.get("moves") or []
                ],
                "releases": [
                    {
                        "issue_id": fill.get("issue_id"),
                        "room": fill.get("room"),
                        "day": fill.get("day"),
                        "start": fill.get("start"),
                        "end": fill.get("end"),
                    }
                    for fill in proposal.get("fills") or []
                ],
            }
            for proposal in piano_proposals or []
            if isinstance(proposal, dict)
        ],
        key=lambda item: (-item["gain"], str(item.get("proposal_id") or "")),
    )
    if room_blockers:
        bottleneck = "compatible_room_saturation"
    elif instructor:
        bottleneck = "instructor_conflict"
    elif incompatible:
        bottleneck = "room_compatibility"
    else:
        bottleneck = "candidate_or_time_data"

    graph_nodes = [{"id": "bottleneck", "kind": "bottleneck", "label": bottleneck}]
    graph_edges = []
    for case in cases or []:
        for issue in case.get("issues") or []:
            issue_id = str(issue.get("issue_id") or "")
            if not issue_id:
                continue
            issue_node = f"issue:{issue_id}"
            graph_nodes.append({"id": issue_node, "kind": "issue", "label": issue_id})
            graph_edges.append({"from": issue_node, "to": "bottleneck", "kind": "blocked_by"})
            for index, trace in enumerate(issue.get("rejection_trace") or []):
                if not isinstance(trace, dict):
                    continue
                blocker_id = f"blocker:{issue_id}:{index}"
                code = str(trace.get("code") or "unknown")
                graph_nodes.append({
                    "id": blocker_id,
                    "kind": "blocker",
                    "label": code,
                    "movable": bool(trace.get("movable")),
                    "room": trace.get("room"),
                })
                graph_edges.append({"from": issue_node, "to": blocker_id, "kind": "rejected_by"})
                if trace.get("room"):
                    room_id = f"room:{trace['room']}"
                    if not any(node["id"] == room_id for node in graph_nodes):
                        graph_nodes.append({"id": room_id, "kind": "room", "label": trace["room"]})
                    graph_edges.append({"from": blocker_id, "to": room_id, "kind": "occupies"})
    for proposal in proposals[:8]:
        proposal_id = str(proposal.get("proposal_id") or "")
        if not proposal_id:
            continue
        proposal_node = f"proposal:{proposal_id}"
        graph_nodes.append({"id": proposal_node, "kind": "leverage", "label": proposal_id, "gain": proposal.get("gain", 0)})
        for release in proposal.get("releases") or []:
            release_id = str(release.get("issue_id") or "")
            if release_id:
                graph_edges.append({"from": proposal_node, "to": f"issue:{release_id}", "kind": "releases"})
    return {
        "primary_bottleneck": bottleneck,
        "issue_count": sum(len(case.get("issues") or []) for case in cases or []),
        "trace_count": len(traces),
        "locked_blockers": locked,
        "movable_blockers": movable,
        "instructor_conflicts": instructor,
        "incompatible_rooms": incompatible,
        "room_saturation": [
            {"room": room, "blocker_count": count}
            for room, count in room_counts.most_common(8)
        ],
        "best_leverage": proposals[:3],
        "leverage_chains": [
            {
                "proposal_id": proposal.get("proposal_id"),
                "trigger": {
                    "instructor": proposal.get("instructor"),
                    "move_count": len(proposal.get("moves") or []),
                },
                "releases": proposal.get("releases") or [],
                "gain": proposal.get("gain", 0),
            }
            for proposal in proposals[:3]
            if proposal.get("releases")
        ],
        "continue_local_adjustment": bool(proposals or room_blockers),
        "graph": {
            "nodes": graph_nodes[:64],
            "edges": graph_edges[:128],
        },
    }
