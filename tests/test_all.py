from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from itertools import product
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data import SCENARIOS, get_scenario  # noqa: E402
from app.fairness import envy_explanation, evaluate_assignment, objective_key  # noqa: E402
from app.ledger import AcceptanceLedger, CommitmentConflict  # noqa: E402
from app.server import Handler  # noqa: E402
from app.solver import (  # noqa: E402
    check_hard_feasible,
    enumerate_all_assignments,
    qualification_conflict_sets,
    solve,
)
from http.server import ThreadingHTTPServer  # noqa: E402


def tiny_problem(hours, capacities=None):
    member_ids = sorted({mid for row in hours.values() for mid in row})
    return {
        "members": [
            {
                "id": mid,
                "name": mid,
                "qualifications": ["通用"],
                "capacity": (capacities or {}).get(mid, 100),
                "cost_rate": 1,
            }
            for mid in member_ids
        ],
        "packages": [
            {
                "id": pid,
                "name": pid,
                "required_qualifications": ["通用"],
                "hours": row,
                "costs": {mid: float(row[mid]) for mid in member_ids},
            }
            for pid, row in hours.items()
        ],
        "constraints": {"together": [], "exclusive": []},
    }


class DataIntegrityTests(unittest.TestCase):
    def test_every_scenario_has_complete_personal_matrices(self):
        for sid, scenario in SCENARIOS.items():
            member_ids = {m["id"] for m in scenario["members"]}
            package_ids = {p["id"] for p in scenario["packages"]}
            self.assertTrue(member_ids, sid)
            self.assertTrue(package_ids, sid)
            for package in scenario["packages"]:
                self.assertEqual(set(package["hours"]), member_ids, (sid, package["id"]))
                self.assertEqual(set(package["costs"]), member_ids, (sid, package["id"]))
                self.assertEqual(set(package["difficulty"]), member_ids, (sid, package["id"]))
                self.assertTrue(
                    all(1 <= value <= 5 for value in package["difficulty"].values()),
                    (sid, package["id"]),
                )
            for group in scenario.get("constraints", {}).get("together", []):
                self.assertTrue(set(group).issubset(package_ids), sid)
            for group in scenario.get("constraints", {}).get("exclusive", []):
                self.assertTrue(set(group).issubset(package_ids), sid)


class EnumerationAndBoundTests(unittest.TestCase):
    def test_micro_has_sixteen_raw_assignments_and_seven_feasible(self):
        result = enumerate_all_assignments(get_scenario("micro"))
        self.assertEqual(result["total_assignments"], 16)
        self.assertEqual(result["feasible_count"], 7)
        self.assertTrue(all(o["matches_solver"] for o in result["optima"].values()))

    def test_solver_matches_independent_bruteforce_for_tradeoff(self):
        scenario = get_scenario("tradeoff")
        result = enumerate_all_assignments(scenario)
        self.assertEqual(result["total_assignments"], 729)
        self.assertGreater(result["feasible_count"], 0)

        member_ids = [m["id"] for m in scenario["members"]]
        package_ids = [p["id"] for p in scenario["packages"]]
        feasible_metrics = []
        for owners in product(member_ids, repeat=len(package_ids)):
            assignment = dict(zip(package_ids, owners))
            if not check_hard_feasible(scenario, assignment):
                feasible_metrics.append(evaluate_assignment(scenario, assignment))

        for objective in ("burden", "ef1", "cost"):
            brute_best = min(feasible_metrics, key=lambda m: objective_key(m, objective))
            solver = solve(scenario, objective)
            self.assertTrue(solver["feasible"], objective)
            self.assertEqual(
                objective_key(solver["metrics"], objective),
                objective_key(brute_best, objective),
                objective,
            )
            self.assertTrue(solver["optimality"]["proven_optimal"])
            self.assertEqual(result["optima"][objective]["matches_solver"], True)

    def test_three_objectives_have_distinct_optimal_arrangements(self):
        scenario = get_scenario("tradeoff")
        plans = {obj: solve(scenario, obj) for obj in ("burden", "ef1", "cost")}
        assignments = {tuple(sorted(p["assignment"].items())) for p in plans.values()}
        self.assertEqual(len(assignments), 3)
        self.assertFalse(plans["burden"]["metrics"]["ef1"])
        self.assertTrue(plans["ef1"]["metrics"]["ef1"])
        self.assertFalse(plans["cost"]["metrics"]["ef1"])
        self.assertLess(
            plans["cost"]["metrics"]["total_cost"],
            plans["burden"]["metrics"]["total_cost"],
        )
        self.assertLess(
            plans["burden"]["metrics"]["max_burden_hours"],
            plans["ef1"]["metrics"]["max_burden_hours"],
        )


class FairnessMetricTests(unittest.TestCase):
    def test_envious_but_ef1_when_removing_largest_own_item(self):
        problem = tiny_problem(
            {
                "x": {"a": 10, "b": 1},
                "y": {"a": 4, "b": 1},
            }
        )
        assignment = {"x": "a", "y": "b"}
        explanation = envy_explanation(problem, assignment, "a", "b")
        self.assertTrue(explanation["is_envious"])
        self.assertTrue(explanation["ef1_pair"])
        self.assertEqual(explanation["best_ef1_residual_gap_hours"], 0)
        self.assertTrue(any(c["eliminates_envy"] for c in explanation["removal_candidates"]))

    def test_two_item_bundle_can_violate_ef1(self):
        problem = tiny_problem(
            {
                "x": {"a": 6, "b": 1},
                "y": {"a": 6, "b": 1},
                "z": {"a": 1, "b": 1},
            }
        )
        assignment = {"x": "a", "y": "a", "z": "b"}
        metrics = evaluate_assignment(problem, assignment)
        pair = next(p for p in metrics["envy_pairs"] if p["observer_id"] == "a" and p["target_id"] == "b")
        self.assertTrue(pair["is_envious"])
        self.assertFalse(pair["ef1_pair"])
        self.assertEqual(pair["raw_best_ef1_residual_gap_hours"], 5)
        self.assertGreaterEqual(metrics["ef1_violation_count"], 1)


class ConstraintAndCommitmentTests(unittest.TestCase):
    def test_together_and_exclusive_are_respected_by_every_plan(self):
        scenario = get_scenario("constraint_lab")
        for objective in ("burden", "ef1", "cost"):
            result = solve(scenario, objective)
            self.assertTrue(result["feasible"], result.get("conflicts"))
            assignment = result["assignment"]
            self.assertEqual(assignment["c1"], assignment["c2"])
            self.assertNotEqual(assignment["c2"], assignment["c3"])
            self.assertEqual(check_hard_feasible(scenario, assignment), [])

    def test_commitment_conflict_names_exact_package_set(self):
        scenario = get_scenario("constraint_lab")
        result = solve(scenario, "burden", {"c1": "m1", "c2": "m2"})
        self.assertFalse(result["feasible"])
        conflict = next(
            c for c in result["conflicts"]
            if c["code"] == "commitment_conflict_inside_together_block"
        )
        self.assertEqual(set(conflict["package_ids"]), {"c1", "c2"})

    def test_accepted_packages_are_locked_and_cannot_improve_objective(self):
        scenario = get_scenario("constraint_lab")
        acceptances = {"c4": "m3"}
        free = solve(scenario, "burden")
        locked = solve(scenario, "burden", acceptances)
        self.assertTrue(locked["feasible"])
        self.assertEqual(locked["assignment"]["c4"], "m3")
        self.assertGreaterEqual(
            locked["metrics"]["max_burden_hours"],
            free["metrics"]["max_burden_hours"] - 1e-9,
        )

    def test_studio_seed_commitment_has_measurable_fairness_loss(self):
        scenario = get_scenario("studio")
        free = solve(scenario, "burden")
        committed = solve(scenario, "burden", {"p_api": "m3"})
        self.assertTrue(free["feasible"])
        self.assertTrue(committed["feasible"])
        self.assertEqual(free["metrics"]["max_burden_hours"], 21)
        self.assertEqual(committed["metrics"]["max_burden_hours"], 24)
        self.assertEqual(committed["assignment"]["p_api"], "m3")

    def test_qualification_gap_returns_concrete_sets_without_relaxation(self):
        scenario = get_scenario("qualification_gap")
        for objective in ("burden", "ef1", "cost"):
            result = solve(scenario, objective)
            self.assertFalse(result["feasible"])

        conflicts = qualification_conflict_sets(scenario)
        self.assertTrue(any(c["package_ids"] == ["g1"] for c in conflicts))
        self.assertTrue(any(c["package_ids"] == ["g2"] for c in conflicts))
        together_conflict = next(
            c for c in conflicts
            if c["code"] == "together_group_has_no_common_qualified_member"
        )
        self.assertEqual(set(together_conflict["package_ids"]), {"g5", "g6"})


class LedgerTests(unittest.TestCase):
    def test_append_acceptance_persists_active_map(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = AcceptanceLedger(path)
            ledger.accept("studio", "p_api", "m3", note="accepted in test")
            self.assertEqual(ledger.active_map("studio"), {"p_api": "m3"})

            reopened = AcceptanceLedger(path)
            self.assertEqual(reopened.active_map("studio"), {"p_api": "m3"})
            record = reopened.records("studio")[0]
            self.assertEqual(record["note"], "accepted in test")

    def test_existing_commitment_cannot_be_moved_by_ordinary_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = AcceptanceLedger(Path(directory) / "ledger.json")
            ledger.accept("studio", "p_api", "m3")
            with self.assertRaises(CommitmentConflict):
                ledger.accept("studio", "p_api", "m1")

            repeated = ledger.accept("studio", "p_api", "m3")
            self.assertTrue(repeated.get("idempotent"))
            self.assertEqual(len(ledger.records("studio")), 1)
            self.assertEqual(ledger.active_map("studio"), {"p_api": "m3"})

            ledger.accept("studio", "p_api", "m1", supersede=True)
            self.assertEqual(ledger.active_map("studio"), {"p_api": "m1"})
            self.assertEqual(len(ledger.records("studio")), 2)

    def test_reset_seed_contains_commitment_conflict_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = AcceptanceLedger(Path(directory) / "ledger.json")
            ledger.reset_to_seed("constraint_lab")
            active = ledger.active_map("constraint_lab")
            self.assertEqual(active, {"c1": "m1", "c2": "m2"})


class HttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))

    def test_static_page_and_core_apis(self):
        health = self.get_json("/api/health")
        self.assertTrue(health["ok"])
        scenarios = self.get_json("/api/scenarios")
        self.assertIn("studio", [s["id"] for s in scenarios["scenarios"]])
        enumeration = self.get_json("/api/enumerate?scenario=micro")
        self.assertEqual(enumeration["total_assignments"], 16)

        with urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as response:
            html = response.read().decode("utf-8")
            self.assertIn("公平工作包分配工作台", html)
        with urlopen(f"http://127.0.0.1:{self.port}/app.js", timeout=5) as response:
            self.assertIn("runEnumeration", response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
