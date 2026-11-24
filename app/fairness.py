"""Fairness and cost metrics for complete work-package assignments."""

from __future__ import annotations

from typing import Any

EPS = 1e-9


def _round(value: float, digits: int = 2) -> float:
    return round(float(value) + 0.0, digits)


def package_map(problem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in problem["packages"]}


def member_map(problem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in problem["members"]}


def bundles_from_assignment(assignment: dict[str, str], member_ids: list[str]) -> dict[str, list[str]]:
    bundles = {mid: [] for mid in member_ids}
    for pid, mid in assignment.items():
        if mid not in bundles:
            raise KeyError(f"unknown member {mid}")
        bundles[mid].append(pid)
    for mid in bundles:
        bundles[mid].sort()
    return bundles


def envy_explanation(
    problem: dict[str, Any],
    assignment: dict[str, str],
    observer_id: str,
    target_id: str,
) -> dict[str, Any]:
    """Explain how observer i values its own and target j's bundle.

    Envy is evaluated with observer i's personal hour estimates.  These are
    chores/burdens, so i envies j when i believes j's bundle would cost i less
    effort than i's own bundle.  Chore EF1 removes one item from i's own bundle.
    """
    packages = package_map(problem)
    members = member_map(problem)
    if observer_id == target_id:
        raise ValueError("observer and target must differ")
    if observer_id not in members or target_id not in members:
        raise KeyError("unknown member")

    own_ids = sorted(pid for pid, mid in assignment.items() if mid == observer_id)
    target_ids = sorted(pid for pid, mid in assignment.items() if mid == target_id)

    own_items = []
    own_value = 0.0
    for pid in own_ids:
        hours = float(packages[pid]["hours"][observer_id])
        own_value += hours
        own_items.append(
            {
                "package_id": pid,
                "package_name": packages[pid]["name"],
                "observer_estimated_hours": hours,
                "observer_difficulty": packages[pid].get("difficulty", {}).get(observer_id),
            }
        )

    target_items = []
    target_value = 0.0
    for pid in target_ids:
        hours = float(packages[pid]["hours"][observer_id])
        hours_owner = float(packages[pid]["hours"][target_id])
        target_value += hours
        target_items.append(
            {
                "package_id": pid,
                "package_name": packages[pid]["name"],
                "observer_estimated_hours": hours,
                "observer_difficulty": packages[pid].get("difficulty", {}).get(observer_id),
                "actual_owner_estimate_hours": hours_owner,
            }
        )

    removal_candidates = []
    for item in own_items:
        removed = float(item["observer_estimated_hours"])
        residual = own_value - removed - target_value
        candidate = dict(item)
        candidate.update(
            {
                "hypothetical_remaining_gap": residual,
                "eliminates_envy": residual <= EPS,
            }
        )
        removal_candidates.append(candidate)

    largest_removable = max(
        (float(p["hours"][observer_id]) for p in [packages[pid] for pid in own_ids]),
        default=0.0,
    )
    best_residual = own_value - largest_removable - target_value
    envy_gap = own_value - target_value
    is_envious = envy_gap > EPS
    ef1_pair = best_residual <= EPS

    if not is_envious:
        plain_language = (
            f"{members[observer_id]['name']} 用自己的估时比较后，并不羡慕 "
            f"{members[target_id]['name']}：自己的束约 {_round(own_value)} 小时，"
            f"对方的束按同一双眼睛只值约 {_round(target_value)} 小时或更高。"
        )
    elif ef1_pair:
        remover = max(removal_candidates, key=lambda x: x["observer_estimated_hours"]) if removal_candidates else None
        remover_text = (
            f"若移走自己的「{remover['package_name']}」，剩余负担差转为 "
            f"{_round(remover['hypothetical_remaining_gap'])}。"
            if remover
            else "自己的束为空。"
        )
        plain_language = (
            f"{members[observer_id]['name']} 确实羡慕 {members[target_id]['name']}，"
            f"负担差约 {_round(envy_gap)} 小时；但这是 EF1 嫉妒，{remover_text}"
        )
    else:
        plain_language = (
            f"{members[observer_id]['name']} 羡慕 {members[target_id]['name']}，"
            f"负担差约 {_round(envy_gap)} 小时；即使移走自己估时最大的一项，"
            f"仍差约 {_round(best_residual)} 小时，因此不满足 EF1。"
        )

    return {
        "observer_id": observer_id,
        "observer_name": members[observer_id]["name"],
        "target_id": target_id,
        "target_name": members[target_id]["name"],
        "observer_self_burden_hours": own_value,
        "observer_values_target_bundle_hours": target_value,
        "envy_gap_hours": envy_gap,
        "is_envious": is_envious,
        "largest_removable_hours": largest_removable,
        "best_ef1_residual_gap_hours": max(0.0, best_residual),
        "raw_best_ef1_residual_gap_hours": best_residual,
        "ef1_pair": ef1_pair,
        "own_items": own_items,
        "target_items": target_items,
        "removal_candidates": removal_candidates,
        "explanation": plain_language,
    }


def evaluate_assignment(problem: dict[str, Any], assignment: dict[str, str]) -> dict[str, Any]:
    """Return burden, cost, utilization and all ordered envy explanations."""
    members = problem["members"]
    member_ids = [m["id"] for m in members]
    packages = package_map(problem)
    bundles = bundles_from_assignment(assignment, member_ids)

    rows = []
    total_cost = 0.0
    total_hours_actual = 0.0
    for member in members:
        mid = member["id"]
        pids = bundles[mid]
        hours = sum(float(packages[pid]["hours"][mid]) for pid in pids)
        cost = sum(float(packages[pid]["costs"][mid]) for pid in pids)
        capacity = float(member["capacity"])
        total_cost += cost
        total_hours_actual += hours
        rows.append(
            {
                "member_id": mid,
                "name": member["name"],
                "color_index": member_ids.index(mid),
                "capacity": capacity,
                "burden_hours": hours,
                "utilization": hours / capacity if capacity else 0.0,
                "utilization_percent": 100.0 * hours / capacity if capacity else 0.0,
                "personal_cost": cost,
                "package_ids": pids,
                "package_count": len(pids),
                "remaining_capacity_hours": capacity - hours,
                "within_capacity": hours <= capacity + EPS,
            }
        )

    max_burden = max((r["burden_hours"] for r in rows), default=0.0)
    max_utilization = max((r["utilization"] for r in rows), default=0.0)
    envy_pairs = []
    for observer in member_ids:
        for target in member_ids:
            if observer == target:
                continue
            envy_pairs.append(envy_explanation(problem, assignment, observer, target))

    envious = [p for p in envy_pairs if p["is_envious"]]
    ef1_violations = [p for p in envy_pairs if not p["ef1_pair"]]
    max_envy_gap = max((max(0.0, p["envy_gap_hours"]) for p in envy_pairs), default=0.0)
    max_ef1_residual = max(
        (p["best_ef1_residual_gap_hours"] for p in ef1_violations), default=0.0
    )
    total_ef1_residual = sum(p["best_ef1_residual_gap_hours"] for p in ef1_violations)

    return {
        "assignment": dict(sorted(assignment.items())),
        "bundles": bundles,
        "members": rows,
        "total_cost": total_cost,
        "total_actual_hours": total_hours_actual,
        "max_burden_hours": max_burden,
        "max_utilization": max_utilization,
        "max_utilization_percent": 100 * max_utilization,
        "envy_pair_count": len(envious),
        "ef1": not ef1_violations,
        "ef1_violation_count": len(ef1_violations),
        "ef1_violation_pairs": [
            {"observer_id": p["observer_id"], "target_id": p["target_id"]}
            for p in ef1_violations
        ],
        "max_envy_gap_hours": max_envy_gap,
        "max_ef1_residual_gap_hours": max_ef1_residual,
        "total_ef1_residual_gap_hours": total_ef1_residual,
        "envy_pairs": envy_pairs,
    }


def objective_key(metrics: dict[str, Any], objective: str) -> tuple[Any, ...]:
    """Lexicographic minimization key.

    The first component is the named objective; later components are
    deterministic tie-breakers, never hidden feasibility relaxations.  Numeric
    components are normalized to 9 decimal places so mathematically equal
    floating-point sums tie rather than creating a noise-driven winner.
    """
    num = lambda value: round(float(value), 9)  # noqa: E731
    if objective in {"burden", "minimax_burden", "max_burden"}:
        return (
            num(metrics["max_burden_hours"]),
            num(metrics["total_cost"]),
            int(metrics["ef1_violation_count"]),
            num(metrics["max_ef1_residual_gap_hours"]),
        )
    if objective in {"ef1", "envy", "fairness"}:
        return (
            int(metrics["ef1_violation_count"]),
            num(metrics["max_ef1_residual_gap_hours"]),
            num(metrics["total_ef1_residual_gap_hours"]),
            int(metrics["envy_pair_count"]),
            num(metrics["max_burden_hours"]),
            num(metrics["total_cost"]),
        )
    if objective in {"cost", "total_cost"}:
        return (
            num(metrics["total_cost"]),
            num(metrics["max_burden_hours"]),
            int(metrics["ef1_violation_count"]),
        )
    raise ValueError(f"unknown objective: {objective}")


def primary_objective_value(metrics: dict[str, Any], objective: str) -> Any:
    key = objective_key(metrics, objective)
    return key[0]
