from modules.scheduler.logic.optimizer_preemption_eviction import block_is_protected


def resolve_grandmaster_conflicts(
    *,
    room_id,
    req,
    conflicts,
    resolve_victim_block,
    check_food_chain,
    relocate_whole_block,
    evict_whole_block,
    append_log,
):
    if not conflicts:
        return True

    for conflict_event in conflicts:
        victim_block = resolve_victim_block(conflict_event)

        if block_is_protected(victim_block):
            append_log(
                f"      ⛔ Preemption Denied: {req['inst']} cannot move pinned or locked block "
                f"{victim_block.get('inst_name')}."
            )
            return False

        if not check_food_chain(req, victim_block):
            append_log(
                f"      ⛔ Preemption Denied: {req['inst']} cannot kick {victim_block['inst_name']} (priority rules)."
            )
            return False

        if relocate_whole_block(victim_block):
            append_log(f"      🔀 Relocated BLOCK '{victim_block['inst_name']}' from {room_id}.")
            continue

        if not evict_whole_block(victim_block):
            append_log(
                f"      ⛔ Preemption Denied: {req['inst']} cannot evict pinned or locked block "
                f"{victim_block.get('inst_name')}."
            )
            return False
        append_log(
            f"      👋 Evicted BLOCK '{victim_block['inst_name']}' from {room_id} (Yielded to higher priority)."
        )

    return True
