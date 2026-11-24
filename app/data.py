"""Fictional datasets for the fair work-package allocation workbench.

All people, packages, rates and estimates are fictional.  Estimates are stored
per member: ``hours[package_id][member_id]`` is that member's own estimate if
they were assigned the package.  Cost is a personal assignment cost.  When a
package does not provide an explicit ``costs`` matrix, it is derived from the
member's fictional hourly cost.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from zlib import crc32

QUAL_BACKEND = "后端"
QUAL_FRONTEND = "前端"
QUAL_DATA = "数据"
QUAL_SECURITY = "安全"
QUAL_QA = "测试"
QUAL_ML = "机器学习"
QUAL_UX = "体验"
QUAL_DEVOPS = "运维"
QUAL_PRODUCT = "产品"
QUAL_GENERAL = "通用"


def _with_derived_costs(scenario: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with a complete per member/package ``costs`` map."""
    result = deepcopy(scenario)
    rates = {m["id"]: float(m.get("cost_rate", 0)) for m in result["members"]}
    member_ids = list(rates)
    for package in result["packages"]:
        package.setdefault("hours", {})
        package.setdefault("costs", {})
        package.setdefault("difficulty", {})
        for mid in member_ids:
            if mid not in package["hours"]:
                raise ValueError(f"{package['id']} is missing hours for {mid}")
            if mid not in package["costs"]:
                package["costs"][mid] = round(
                    float(package["hours"][mid]) * rates[mid], 2
                )
            if mid not in package["difficulty"]:
                # Deterministic fictional 1--5 difficulty perception.  It is
                # kept separate so it never silently changes hour capacities.
                hours = float(package["hours"][mid])
                base = max(1, min(5, int(round(hours / 4.0))))
                wobble = crc32(f"{package['id']}:{mid}".encode("utf-8")) % 3 - 1
                package["difficulty"][mid] = max(1, min(5, base + wobble))
    return result


STUDIO: dict[str, Any] = {
    "id": "studio",
    "name": "星澜数字产品交付组",
    "description": (
        "9 个不可拆工作包，含同包绑定、互斥职责分离、资格门槛和差异很大的个人估时。"
    ),
    "currency": "¥",
    "members": [
        {
            "id": "m1",
            "name": "林岚",
            "role": "高级后端/安全",
            "qualifications": [QUAL_BACKEND, QUAL_DATA, QUAL_SECURITY],
            "capacity": 42,
            "cost_rate": 180,
        },
        {
            "id": "m2",
            "name": "周屿",
            "role": "前端/体验",
            "qualifications": [QUAL_FRONTEND, QUAL_UX, QUAL_DATA, QUAL_PRODUCT],
            "capacity": 36,
            "cost_rate": 150,
        },
        {
            "id": "m3",
            "name": "陈禾",
            "role": "后端/测试",
            "qualifications": [QUAL_BACKEND, QUAL_QA, QUAL_DATA],
            "capacity": 40,
            "cost_rate": 110,
        },
        {
            "id": "m4",
            "name": "许知夏",
            "role": "机器学习/数据",
            "qualifications": [QUAL_ML, QUAL_DATA, QUAL_QA],
            "capacity": 34,
            "cost_rate": 160,
        },
        {
            "id": "m5",
            "name": "赵野",
            "role": "运维/安全",
            "qualifications": [QUAL_DEVOPS, QUAL_SECURITY, QUAL_BACKEND],
            "capacity": 38,
            "cost_rate": 140,
        },
    ],
    "packages": [
        {
            "id": "p_auth",
            "name": "权限内核改造",
            "required_qualifications": [QUAL_BACKEND, QUAL_SECURITY],
            "hours": {"m1": 8, "m2": 15, "m3": 11, "m4": 14, "m5": 9},
        },
        {
            "id": "p_audit",
            "name": "合规审计报表",
            "required_qualifications": [QUAL_DATA, QUAL_SECURITY],
            "hours": {"m1": 6, "m2": 10, "m3": 9, "m4": 8, "m5": 13},
        },
        {
            "id": "p_pipeline",
            "name": "实时数据管道",
            "required_qualifications": [QUAL_DATA, QUAL_BACKEND],
            "hours": {"m1": 10, "m2": 16, "m3": 12, "m4": 9, "m5": 15},
        },
        {
            "id": "p_dashboard",
            "name": "经营指标看板",
            "required_qualifications": [QUAL_FRONTEND, QUAL_DATA],
            "hours": {"m1": 14, "m2": 8, "m3": 15, "m4": 11, "m5": 18},
        },
        {
            "id": "p_eval",
            "name": "模型评测台",
            "required_qualifications": [QUAL_ML, QUAL_QA],
            "hours": {"m1": 15, "m2": 13, "m3": 12, "m4": 7, "m5": 18},
        },
        {
            "id": "p_release",
            "name": "安全发布流水线",
            "required_qualifications": [QUAL_DEVOPS, QUAL_SECURITY],
            "hours": {"m1": 10, "m2": 20, "m3": 14, "m4": 16, "m5": 7},
        },
        {
            "id": "p_e2e",
            "name": "端到端回归体系",
            "required_qualifications": [QUAL_QA],
            "hours": {"m1": 12, "m2": 11, "m3": 8, "m4": 10, "m5": 13},
        },
        {
            "id": "p_demo",
            "name": "客户演示原型",
            "required_qualifications": [QUAL_FRONTEND, QUAL_UX],
            "hours": {"m1": 16, "m2": 6, "m3": 14, "m4": 12, "m5": 17},
        },
        {
            "id": "p_api",
            "name": "开放 API 限流",
            "required_qualifications": [QUAL_BACKEND],
            "hours": {"m1": 7, "m2": 13, "m3": 8, "m4": 12, "m5": 9},
        },
    ],
    "constraints": {
        "together": [
            ["p_auth", "p_audit"],
        ],
        "exclusive": [
            ["p_pipeline", "p_eval"],
            ["p_api", "p_release"],
            ["p_e2e", "p_eval"],
        ],
    },
}


MICRO: dict[str, Any] = {
    "id": "micro",
    "name": "双人四包枚举核对实例",
    "description": "2^4=16 种原始分配，可在页面和单元测试中逐一枚举核对。",
    "currency": "¥",
    "members": [
        {
            "id": "a",
            "name": "阿宁",
            "role": "虚构工程师 A",
            "qualifications": [QUAL_GENERAL],
            "capacity": 15,
            "cost_rate": 150,
        },
        {
            "id": "b",
            "name": "小柯",
            "role": "虚构工程师 B",
            "qualifications": [QUAL_GENERAL],
            "capacity": 15,
            "cost_rate": 100,
        },
    ],
    "packages": [
        {
            "id": "q1",
            "name": "小功能甲",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"a": 6, "b": 9},
        },
        {
            "id": "q2",
            "name": "小功能乙",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"a": 7, "b": 4},
        },
        {
            "id": "q3",
            "name": "迁移脚本",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"a": 5, "b": 8},
        },
        {
            "id": "q4",
            "name": "验收自动化",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"a": 4, "b": 3},
        },
    ],
    "constraints": {"together": [], "exclusive": []},
}


TRADEOFF: dict[str, Any] = {
    "id": "tradeoff",
    "name": "三目标冲突标本",
    "description": "3^6=729 种分配；最小最大负担、EF1 与最低成本的最优安排互不相同。",
    "currency": "¥",
    "members": [
        {
            "id": "m1",
            "name": "顾一",
            "qualifications": [QUAL_GENERAL],
            "capacity": 24,
            "cost_rate": 140,
        },
        {
            "id": "m2",
            "name": "蓝二",
            "qualifications": [QUAL_GENERAL],
            "capacity": 24,
            "cost_rate": 140,
        },
        {
            "id": "m3",
            "name": "沈三",
            "qualifications": [QUAL_GENERAL],
            "capacity": 24,
            "cost_rate": 90,
        },
    ],
    "packages": [
        {
            "id": "t1",
            "name": "网关限流",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 9, "m2": 4, "m3": 10},
        },
        {
            "id": "t2",
            "name": "对账报表",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 5, "m2": 9, "m3": 11},
        },
        {
            "id": "t3",
            "name": "权限巡检",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 4, "m2": 11, "m3": 10},
        },
        {
            "id": "t4",
            "name": "全链路压测",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 6, "m2": 3, "m3": 8},
        },
        {
            "id": "t5",
            "name": "数据修复",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 12, "m2": 4, "m3": 4},
        },
        {
            "id": "t6",
            "name": "监控告警",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 11, "m2": 6, "m3": 10},
        },
    ],
    "constraints": {"together": [], "exclusive": []},
}


CONSTRAINT_LAB: dict[str, Any] = {
    "id": "constraint_lab",
    "name": "依赖与承诺冲突实验",
    "description": "c1/c2 必须同人；c2/c3 互斥。用于测试同包依赖、异估时和锁定冲突。",
    "currency": "分",
    "members": [
        {
            "id": "m1",
            "name": "一诺",
            "qualifications": [QUAL_GENERAL],
            "capacity": 20,
            "cost_rate": 10,
        },
        {
            "id": "m2",
            "name": "二则",
            "qualifications": [QUAL_GENERAL],
            "capacity": 20,
            "cost_rate": 12,
        },
        {
            "id": "m3",
            "name": "三禾",
            "qualifications": [QUAL_GENERAL],
            "capacity": 20,
            "cost_rate": 9,
        },
    ],
    "packages": [
        {
            "id": "c1",
            "name": "领域建模",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 4, "m2": 7, "m3": 6},
        },
        {
            "id": "c2",
            "name": "数据结构改造",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 5, "m2": 3, "m3": 8},
        },
        {
            "id": "c3",
            "name": "独立验收",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 6, "m2": 4, "m3": 5},
        },
        {
            "id": "c4",
            "name": "发布说明",
            "required_qualifications": [QUAL_GENERAL],
            "hours": {"m1": 3, "m2": 5, "m3": 2},
        },
    ],
    "constraints": {
        "together": [["c1", "c2"]],
        "exclusive": [["c2", "c3"]],
    },
}


QUALIFICATION_GAP: dict[str, Any] = {
    "id": "qualification_gap",
    "name": "硬资格无解实例",
    "description": "缺少量子安全/大型机资格，且一对同包工作没有任何成员同时具备资格。",
    "currency": "¥",
    "members": [
        {
            "id": "m1",
            "name": "贺明",
            "qualifications": [QUAL_BACKEND, QUAL_DATA],
            "capacity": 40,
            "cost_rate": 150,
        },
        {
            "id": "m2",
            "name": "唐棠",
            "qualifications": [QUAL_FRONTEND, QUAL_UX],
            "capacity": 36,
            "cost_rate": 140,
        },
        {
            "id": "m3",
            "name": "罗森",
            "qualifications": [QUAL_QA, QUAL_BACKEND],
            "capacity": 38,
            "cost_rate": 120,
        },
    ],
    "packages": [
        {
            "id": "g1",
            "name": "量子加密迁移",
            "required_qualifications": ["量子安全"],
            "hours": {"m1": 8, "m2": 12, "m3": 10},
        },
        {
            "id": "g2",
            "name": "大型机批处理接管",
            "required_qualifications": ["大型机"],
            "hours": {"m1": 14, "m2": 20, "m3": 12},
        },
        {
            "id": "g3",
            "name": "后端服务拆分",
            "required_qualifications": [QUAL_BACKEND],
            "hours": {"m1": 7, "m2": 15, "m3": 9},
        },
        {
            "id": "g4",
            "name": "交互走查",
            "required_qualifications": [QUAL_UX],
            "hours": {"m1": 12, "m2": 5, "m3": 14},
        },
        {
            "id": "g5",
            "name": "必须同源的后端+体验包 A",
            "required_qualifications": [QUAL_BACKEND],
            "hours": {"m1": 6, "m2": 12, "m3": 8},
        },
        {
            "id": "g6",
            "name": "必须同源的后端+体验包 B",
            "required_qualifications": [QUAL_UX],
            "hours": {"m1": 10, "m2": 4, "m3": 13},
        },
    ],
    "constraints": {
        "together": [["g5", "g6"]],
        "exclusive": [],
    },
}


RAW_SCENARIOS = {
    "studio": STUDIO,
    "tradeoff": TRADEOFF,
    "micro": MICRO,
    "constraint_lab": CONSTRAINT_LAB,
    "qualification_gap": QUALIFICATION_GAP,
}

SCENARIOS: dict[str, dict[str, Any]] = {
    sid: _with_derived_costs(scenario) for sid, scenario in RAW_SCENARIOS.items()
}

# Fictional accepted-task ledger seed.  The conflicting lab records are
# intentionally factual commitments; the solver must report the conflict
# instead of quietly changing estimates or reassigning accepted work.
SEED_LEDGER: dict[str, list[dict[str, Any]]] = {
    "studio": [
        {
            "scenario": "studio",
            "package_id": "p_api",
            "member_id": "m3",
            "source": "seed",
            "note": "陈禾已接受开放 API 限流，并承诺本周先给出限流方案",
        }
    ],
    "constraint_lab": [
        {
            "scenario": "constraint_lab",
            "package_id": "c1",
            "member_id": "m1",
            "source": "seed",
            "note": "一诺已接受领域建模",
        },
        {
            "scenario": "constraint_lab",
            "package_id": "c2",
            "member_id": "m2",
            "source": "seed",
            "note": "二则已接受数据结构改造；与 c1 必须同人冲突",
        },
    ],
    "micro": [],
    "tradeoff": [],
    "qualification_gap": [],
}


def get_scenario(scenario_id: str) -> dict[str, Any]:
    if scenario_id not in SCENARIOS:
        raise KeyError(f"unknown scenario: {scenario_id}")
    return deepcopy(SCENARIOS[scenario_id])


def scenario_summaries() -> list[dict[str, Any]]:
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "description": s["description"],
            "member_count": len(s["members"]),
            "package_count": len(s["packages"]),
        }
        for s in SCENARIOS.values()
    ]
