"""Exact small-instance solver and independent brute-force enumeration.

The solver collapses must-be-same packages into blocks, then performs a
complete depth-first search over block owners.  Capacity, qualification,
exclusion and commitment locks are hard constraints.  Every feasible leaf is
evaluated, so returned optima are certified for the supplied finite instance.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations, product
from typing import Any, Iterable

from .fairness import evaluate_assignment, objective_key, primary_objective_value

EPS = 1e-9
OBJECTIVES = ("burden", "ef1", "cost")


class UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {x: x for x in items}
        self.rank = {x: 0 for x in items}

    def find(self, x: str) -> str:
        parent = self.parent[x]
        if parent != x:
            self.parent[x] = self.find(parent)
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def with_capacity_overrides(problem: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(problem)
    if not overrides:
        return result
    valid = {m["id"] for m in result["members"]}
    for mid, capacity in overrides.items():
        if mid not in valid:
            raise KeyError(f"unknown member {mid}")
        capacity = float(capacity)
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        for member in result["members"]:
            if member["id"] == mid:
                member["capacity"] = capacity
    return result


def _constraint_lists(problem: dict[str, Any]) -> tuple[list[list[str]], list[list[str]]]:
    constraints = problem.get("constraints", {}) or {}
    together = [list(group) for group in constraints.get("together", [])]
    exclusive = [list(group) for group in constraints.get("exclusive", [])]
    return together, exclusive


def qualification_conflict_sets(problem: dict[str, Any]) -> list[dict[str, Any]]:
    """Return concrete package sets that hard qualifications make impossible."""
    packages = {p["id"]: p for p in problem["packages"]}
    members = problem["members"]
    conflicts: list[dict[str, Any]] = []

    for pid, package in packages.items():
        required = set(package.get("required_qualifications", []))
        qualified = [
            m["id"] for m in members if required.issubset(set(m.get("qualifications", [])))
        ]
        if not qualified:
            conflicts.append(
                {
                    "code": "no_qualified_member",
                    "package_ids": [pid],
                    "package_names": [package["name"]],
                    "required_qualifications": sorted(required),
                    "message": (
                        f"工作包 {pid}「{package['name']}」要求 {sorted(required)}，"
                        "但没有成员具备全部资格。"
                    ),
                }
            )

    together, _ = _constraint_lists(problem)
    for group in together:
        missing = [pid for pid in group if pid not in packages]
        if missing:
            conflicts.append(
                {
                    "code": "unknown_package_in_together",
                    "package_ids": missing,
                    "message": f"同包约束引用了不存在的工作包：{missing}",
                }
            )
            continue
        if len(group) < 2:
            continue
        required = set()
        for pid in group:
            required.update(packages[pid].get("required_qualifications", []))
        qualified = [
            m["id"]
            for m in members
            if required.issubset(set(m.get("qualifications", [])))
        ]
        individually_ok = all(
            any(
                set(packages[pid].get("required_qualifications", [])).issubset(
                    set(m.get("qualifications", []))
                )
                for m in members
            )
            for pid in group
        )
        if not qualified:
            conflicts.append(
                {
                    "code": "together_group_has_no_common_qualified_member",
                    "package_ids": list(group),
                    "package_names": [packages[pid]["name"] for pid in group],
                    "required_qualifications": sorted(required),
                    "individually_assignable": individually_ok,
                    "message": (
                        "必须由同一人完成的工作包集合 "
                        f"{group} 要求合并资格 {sorted(required)}，但没有成员同时满足。"
                    ),
                }
            )
    return conflicts


def build_blocks(
    problem: dict[str, Any], acceptances: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], bool], list[dict[str, Any]]]:
    """Build same-person blocks and block-level exclusion edges."""
    acceptances = dict(acceptances or {})
    packages = {p["id"]: p for p in problem["packages"]}
    members = {m["id"]: m for m in problem["members"]}
    package_ids = list(packages)
    conflicts: list[dict[str, Any]] = []

    for pid in acceptances:
        if pid not in packages:
            conflicts.append(
                {"code": "unknown_accepted_package", "package_ids": [pid], "message": f"台账接受了未知工作包 {pid}"}
            )
        if acceptances[pid] not in members:
            conflicts.append(
                {
                    "code": "unknown_accepted_member",
                    "package_ids": [pid],
                    "member_id": acceptances[pid],
                    "message": f"台账把 {pid} 锁定给未知成员 {acceptances[pid]}",
                }
            )

    uf = UnionFind(package_ids)
    together, exclusive_groups = _constraint_lists(problem)
    for group in together:
        valid = [pid for pid in group if pid in packages]
        for pid in valid[1:]:
            uf.union(valid[0], pid)

    roots: dict[str, list[str]] = {}
    for pid in package_ids:
        roots.setdefault(uf.find(pid), []).append(pid)

    root_to_block = {root: f"b{i+1}" for i, root in enumerate(sorted(roots))}
    blocks: list[dict[str, Any]] = []
    pid_to_block: dict[str, str] = {}

    for root, pids in sorted(roots.items(), key=lambda kv: root_to_block[kv[0]]):
        bid = root_to_block[root]
        for pid in pids:
            pid_to_block[pid] = bid

        required = set()
        for pid in pids:
            required.update(packages[pid].get("required_qualifications", []))

        member_options: dict[str, dict[str, float | bool]] = {}
        for mid, member in members.items():
            qualified = required.issubset(set(member.get("qualifications", [])))
            hours = sum(float(packages[pid]["hours"][mid]) for pid in pids)
            cost = sum(float(packages[pid]["costs"][mid]) for pid in pids)
            member_options[mid] = {
                "qualified": qualified,
                "hours": hours,
                "cost": cost,
                "block_fits_capacity": hours <= float(member["capacity"]) + EPS,
            }

        accepted_by: dict[str, list[str]] = {}
        for pid in pids:
            mid = acceptances.get(pid)
            if mid is not None:
                accepted_by.setdefault(mid, []).append(pid)
        forced_members = list(accepted_by)
        forced_member = forced_members[0] if len(forced_members) == 1 else None
        locked_pids = [pid for pid in pids if pid in acceptances]

        if len(forced_members) > 1:
            flat = [pid for pids_ in accepted_by.values() for pid in pids_]
            conflicts.append(
                {
                    "code": "commitment_conflict_inside_together_block",
                    "block_id": bid,
                    "package_ids": sorted(flat),
                    "accepted_by": {mid: sorted(pids_) for mid, pids_ in accepted_by.items()},
                    "message": (
                        f"同包块 {sorted(pids)} 中的已接受工作包被台账承诺给不同成员："
                        f"{accepted_by}。"
                    ),
                }
            )

        if forced_member is not None and forced_member in members:
            option = member_options[forced_member]
            if not option["qualified"]:
                conflicts.append(
                    {
                        "code": "commitment_member_lacks_qualification",
                        "block_id": bid,
                        "member_id": forced_member,
                        "package_ids": sorted(pids),
                        "message": f"已接受给 {forced_member} 的块 {sorted(pids)} 不满足硬资格。",
                    }
                )
            if not option["block_fits_capacity"]:
                conflicts.append(
                    {
                        "code": "commitment_exceeds_capacity_alone",
                        "block_id": bid,
                        "member_id": forced_member,
                        "package_ids": sorted(pids),
                        "required_hours": option["hours"],
                        "capacity": members[forced_member]["capacity"],
                        "message": (
                            f"已承诺给 {forced_member} 的块自身估时 {option['hours']} "
                            f"超过容量 {members[forced_member]['capacity']}。"
                        ),
                    }
                )

        candidates = [
            mid
            for mid, option in member_options.items()
            if option["qualified"] and option["block_fits_capacity"]
        ]
        if forced_member is not None:
            # Keep the forced member even if locally impossible so the explicit
            # conflict above remains the reported reason.
            candidates = [forced_member]

        if not candidates and forced_member is None:
            qualified_members = [
                mid for mid, option in member_options.items() if option["qualified"]
            ]
            if qualified_members:
                conflicts.append(
                    {
                        "code": "block_exceeds_every_qualified_capacity",
                        "block_id": bid,
                        "package_ids": sorted(pids),
                        "qualified_members": qualified_members,
                        "required_qualifications": sorted(required),
                        "message": (
                            f"工作包集合 {sorted(pids)} 的资格可由 {qualified_members} 满足，"
                            "但按各成员自己的估时，整块工时超过他们任何人的容量。"
                        ),
                    }
                )
            # If nobody is qualified, qualification_conflict_sets() below emits
            # the concrete single-package or together-group set.  Avoid a
            # second generic diagnostic for the same qualification failure.

        blocks.append(
            {
                "id": bid,
                "root": root,
                "package_ids": sorted(pids),
                "required_qualifications": sorted(required),
                "options": member_options,
                "candidates": candidates,
                "forced_member": forced_member,
                "locked_package_ids": sorted(locked_pids),
                "accepted_by": accepted_by,
            }
        )

    exclusion_pairs: dict[tuple[str, str], bool] = {}
    for group in exclusive_groups:
        valid = [pid for pid in group if pid in packages]
        for a, b in combinations(sorted(set(valid)), 2):
            ba, bb = pid_to_block[a], pid_to_block[b]
            if ba == bb:
                conflicts.append(
                    {
                        "code": "exclusive_packages_forced_together",
                        "package_ids": [a, b],
                        "block_id": ba,
                        "message": f"互斥工作包 {a} 与 {b} 同时被同包依赖要求由一人完成。",
                    }
                )
            else:
                exclusion_pairs[tuple(sorted((ba, bb)))] = True

    # Qualification diagnostics are useful even when block construction has
    # already represented them.  Include the human-readable concrete sets.
    conflicts.extend(qualification_conflict_sets(problem))
    return blocks, exclusion_pairs, conflicts


def solve(
    problem: dict[str, Any],
    objective: str = "burden",
    acceptances: dict[str, str] | None = None,
    capacity_overrides: dict[str, Any] | None = None,
    max_nodes: int = 2_000_000,
) -> dict[str, Any]:
    """Find a lexicographically optimal complete assignment."""
    if objective not in OBJECTIVES and objective not in {"max_burden", "envy", "fairness", "total_cost"}:
        raise ValueError(f"unsupported objective {objective}")
    problem = with_capacity_overrides(problem, capacity_overrides)
    acceptances = dict(acceptances or {})
    members = problem["members"]
    member_ids = [m["id"] for m in members]
    capacities = {m["id"]: float(m["capacity"]) for m in members}

    blocks, exclusion_pairs, conflicts = build_blocks(problem, acceptances)
    if conflicts:
        return {
            "feasible": False,
            "objective": objective,
            "assignment": None,
            "metrics": None,
            "conflicts": _dedupe_conflicts(conflicts),
            "optimality": {"proven_optimal": False, "method": "not_started"},
        }

    block_by_id = {b["id"]: b for b in blocks}
    # Most constrained first: forced blocks, few candidates, large work.
    ordered = sorted(
        blocks,
        key=lambda b: (
            0 if b["forced_member"] else 1,
            len(b["candidates"]),
            -max(float(b["options"][m]["hours"]) for m in member_ids),
            b["id"],
        ),
    )

    loads = {mid: 0.0 for mid in member_ids}
    owner: dict[str, str] = {}
    nodes = 0
    pruned = 0
    feasible_leaves = 0
    best_key: tuple[Any, ...] | None = None
    best_metrics: dict[str, Any] | None = None

    def excluded_from(block_id: str, mid: str) -> bool:
        for other_id, other_owner in owner.items():
            if other_owner != mid:
                continue
            pair = tuple(sorted((block_id, other_id)))
            if pair in exclusion_pairs:
                return True
        return False

    def dfs(index: int) -> None:
        nonlocal nodes, pruned, feasible_leaves, best_key, best_metrics
        nodes += 1
        if nodes > max_nodes:
            raise RuntimeError(f"solver node limit {max_nodes} exceeded")
        if index == len(ordered):
            assignment: dict[str, str] = {}
            for block in blocks:
                mid = owner[block["id"]]
                for pid in block["package_ids"]:
                    assignment[pid] = mid
            metrics = evaluate_assignment(problem, assignment)
            feasible_leaves += 1
            key = objective_key(metrics, objective)
            if best_key is None or key < best_key:
                best_key = key
                best_metrics = metrics
            return

        block = ordered[index]
        bid = block["id"]
        candidates = list(block["candidates"])
        # Try low-hour options first to find a good incumbent early.
        candidates.sort(key=lambda mid: float(block["options"][mid]["hours"]))
        for mid in candidates:
            hours = float(block["options"][mid]["hours"])
            if loads[mid] + hours > capacities[mid] + EPS:
                pruned += 1
                continue
            if excluded_from(bid, mid):
                pruned += 1
                continue
            loads[mid] += hours
            owner[bid] = mid
            dfs(index + 1)
            loads[mid] -= hours
            del owner[bid]

    try:
        dfs(0)
    except RuntimeError as exc:
        return {
            "feasible": False,
            "objective": objective,
            "assignment": None,
            "metrics": None,
            "conflicts": [{"code": "search_limit", "message": str(exc)}],
            "optimality": {
                "proven_optimal": False,
                "method": "depth_first_search_limit",
                "nodes": nodes,
            },
        }

    if best_metrics is None:
        return {
            "feasible": False,
            "objective": objective,
            "assignment": None,
            "metrics": None,
            "conflicts": [
                {
                    "code": "no_assignment_after_complete_search",
                    "message": (
                        "资格和同包集合存在候选，但容量与互斥约束的组合没有可行排列；"
                        "求解器未修改任何估时或资格。"
                    ),
                }
            ],
            "optimality": {
                "proven_optimal": True,
                "method": "complete_depth_first_search",
                "nodes": nodes,
                "feasible_leaves": 0,
                "pruned_branches": pruned,
            },
        }

    block_results = []
    for block in blocks:
        bid = block["id"]
        mid = best_metrics["assignment"][block["package_ids"][0]]
        block_results.append(
            {
                "block_id": bid,
                "package_ids": block["package_ids"],
                "owner_id": mid,
                "forced_member": block["forced_member"],
                "locked_package_ids": block["locked_package_ids"],
                "is_commitment_locked": bool(block["locked_package_ids"]),
            }
        )

    return {
        "feasible": True,
        "objective": objective,
        "assignment": best_metrics["assignment"],
        "metrics": best_metrics,
        "blocks": block_results,
        "locks": acceptances,
        "conflicts": [],
        "optimality": {
            "proven_optimal": True,
            "method": "complete_depth_first_search_over_same_owner_blocks",
            "nodes": nodes,
            "feasible_leaves": feasible_leaves,
            "pruned_branches": pruned,
            "block_count": len(blocks),
            "exclusion_edge_count": len(exclusion_pairs),
            "primary_value": primary_objective_value(best_metrics, objective),
        },
    }


def _dedupe_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for conflict in conflicts:
        key = (
            conflict.get("code"),
            tuple(conflict.get("package_ids", [])),
            conflict.get("block_id"),
            conflict.get("member_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(conflict)
    return result


def check_hard_feasible(
    problem: dict[str, Any],
    assignment: dict[str, str],
    acceptances: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Independent hard-constraint checker used by brute-force enumeration."""
    acceptances = acceptances or {}
    packages = {p["id"]: p for p in problem["packages"]}
    members = {m["id"]: m for m in problem["members"]}
    violations: list[dict[str, Any]] = []

    if set(assignment) != set(packages):
        violations.append({"code": "incomplete_assignment", "message": "每个工作包必须恰好分配一次。"})
        return violations

    for pid, mid in assignment.items():
        if mid not in members:
            violations.append({"code": "unknown_member", "package_ids": [pid], "member_id": mid})
            continue
        required = set(packages[pid].get("required_qualifications", []))
        if not required.issubset(set(members[mid].get("qualifications", []))):
            violations.append(
                {"code": "qualification", "package_ids": [pid], "member_id": mid}
            )
        if pid in acceptances and acceptances[pid] != mid:
            violations.append(
                {
                    "code": "commitment_lock_moved",
                    "package_ids": [pid],
                    "expected_member_id": acceptances[pid],
                    "member_id": mid,
                }
            )

    loads = {mid: 0.0 for mid in members}
    for pid, mid in assignment.items():
        if mid in members:
            loads[mid] += float(packages[pid]["hours"][mid])
    for mid, load in loads.items():
        if load > float(members[mid]["capacity"]) + EPS:
            violations.append(
                {
                    "code": "capacity",
                    "member_id": mid,
                    "load_hours": load,
                    "capacity": members[mid]["capacity"],
                }
            )

    together, exclusive = _constraint_lists(problem)
    for group in together:
        owners = {assignment.get(pid) for pid in group if pid in assignment}
        if len(owners) > 1:
            violations.append({"code": "together", "package_ids": group, "owners": sorted(o for o in owners if o)})

    for group in exclusive:
        for a, b in combinations(group, 2):
            if a in assignment and b in assignment and assignment[a] == assignment[b]:
                violations.append({"code": "exclusive", "package_ids": [a, b], "member_id": assignment[a]})

    return violations


def enumerate_all_assignments(
    problem: dict[str, Any],
    acceptances: dict[str, str] | None = None,
    capacity_overrides: dict[str, Any] | None = None,
    max_assignments: int = 4096,
) -> dict[str, Any]:
    """Brute-force every raw package assignment for a tiny instance."""
    problem = with_capacity_overrides(problem, capacity_overrides)
    member_ids = [m["id"] for m in problem["members"]]
    package_ids = [p["id"] for p in problem["packages"]]
    total = len(member_ids) ** len(package_ids)
    if total > max_assignments:
        raise ValueError(f"refusing to enumerate {total} assignments (limit {max_assignments})")

    rows = []
    feasible_rows = []
    for index, owner_tuple in enumerate(product(member_ids, repeat=len(package_ids))):
        assignment = dict(zip(package_ids, owner_tuple))
        violations = check_hard_feasible(problem, assignment, acceptances)
        row: dict[str, Any] = {
            "index": index,
            "assignment": assignment,
            "feasible": not violations,
            "violation_codes": sorted({v["code"] for v in violations}),
        }
        if not violations:
            metrics = evaluate_assignment(problem, assignment)
            row.update(
                {
                    "max_burden_hours": metrics["max_burden_hours"],
                    "total_cost": metrics["total_cost"],
                    "ef1": metrics["ef1"],
                    "ef1_violation_count": metrics["ef1_violation_count"],
                    "max_ef1_residual_gap_hours": metrics["max_ef1_residual_gap_hours"],
                    "envy_pair_count": metrics["envy_pair_count"],
                    "objective_keys": {
                        obj: list(objective_key(metrics, obj)) for obj in OBJECTIVES
                    },
                }
            )
            feasible_rows.append((row, metrics))
        rows.append(row)

    optima: dict[str, Any] = {}
    for objective in OBJECTIVES:
        if feasible_rows:
            best_row, best_metrics = min(
                feasible_rows, key=lambda pair: objective_key(pair[1], objective)
            )
            optima[objective] = {
                "assignment": best_row["assignment"],
                "primary_value": primary_objective_value(best_metrics, objective),
                "objective_key": list(objective_key(best_metrics, objective)),
            }
            solver_result = solve(problem, objective, acceptances)
            solver_key = (
                list(objective_key(solver_result["metrics"], objective))
                if solver_result["feasible"]
                else None
            )
            optima[objective]["solver_key"] = solver_key
            optima[objective]["matches_solver"] = solver_key == optima[objective]["objective_key"]

    return {
        "method": "exhaustive_cartesian_product",
        "total_assignments": total,
        "feasible_count": len(feasible_rows),
        "infeasible_count": total - len(feasible_rows),
        "rows": rows,
        "optima": optima,
    }


def compare_capacity_and_commitments(
    problem: dict[str, Any],
    acceptances: dict[str, str] | None = None,
    capacity_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Solve free vs committed plans at baseline and adjusted capacities."""
    acceptances = dict(acceptances or {})

    def one_capacity_set(overrides: dict[str, Any] | None) -> dict[str, Any]:
        free = {obj: solve(problem, obj, None, overrides) for obj in OBJECTIVES}
        committed = {
            obj: solve(problem, obj, acceptances or None, overrides)
            for obj in OBJECTIVES
        }
        loss: dict[str, Any] = {}
        for obj in OBJECTIVES:
            f, c = free[obj], committed[obj]
            if not f["feasible"]:
                loss[obj] = {"free_feasible": False, "committed_feasible": c["feasible"]}
            elif not c["feasible"]:
                loss[obj] = {
                    "free_feasible": True,
                    "committed_feasible": False,
                    "delta_primary": None,
                    "message": "承诺集合使问题无可行解",
                    "conflicts": c["conflicts"],
                }
            else:
                fp = primary_objective_value(f["metrics"], obj)
                cp = primary_objective_value(c["metrics"], obj)
                loss[obj] = {
                    "free_feasible": True,
                    "committed_feasible": True,
                    "free_primary": fp,
                    "committed_primary": cp,
                    "delta_primary": round(float(cp) - float(fp), 2),
                    "free_ef1": f["metrics"]["ef1"],
                    "committed_ef1": c["metrics"]["ef1"],
                    "delta_ef1_violation_count": c["metrics"]["ef1_violation_count"]
                    - f["metrics"]["ef1_violation_count"],
                }
        return {"free": free, "committed": committed, "commitment_loss": loss}

    baseline = one_capacity_set(None)
    adjusted = one_capacity_set(capacity_overrides) if capacity_overrides else None
    capacity_delta: dict[str, Any] | None = None
    if adjusted:
        capacity_delta = {}
        for mode in ("free", "committed"):
            capacity_delta[mode] = {}
            for obj in OBJECTIVES:
                b = baseline[mode][obj]
                a = adjusted[mode][obj]
                if b["feasible"] and a["feasible"]:
                    capacity_delta[mode][obj] = {
                        "baseline_primary": primary_objective_value(b["metrics"], obj),
                        "adjusted_primary": primary_objective_value(a["metrics"], obj),
                        "delta_primary": round(
                            float(primary_objective_value(a["metrics"], obj))
                            - float(primary_objective_value(b["metrics"], obj)),
                            2,
                        ),
                        "baseline_max_burden": b["metrics"]["max_burden_hours"],
                        "adjusted_max_burden": a["metrics"]["max_burden_hours"],
                        "baseline_cost": b["metrics"]["total_cost"],
                        "adjusted_cost": a["metrics"]["total_cost"],
                    }
                else:
                    capacity_delta[mode][obj] = {
                        "baseline_feasible": b["feasible"],
                        "adjusted_feasible": a["feasible"],
                    }

    return {
        "baseline": baseline,
        "adjusted": adjusted,
        "capacity_delta": capacity_delta,
        "acceptances": acceptances,
        "capacity_overrides": capacity_overrides or {},
    }
