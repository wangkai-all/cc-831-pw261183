"use strict";

const OBJECTIVES = [
  { id: "burden", label: "最小最大负担", unit: "h" },
  { id: "ef1", label: "EF1 嫉妒", unit: "" },
  { id: "cost", label: "总成本", unit: "" },
];

const ENUM_IDS = ["micro", "tradeoff", "constraint_lab", "qualification_gap"];

const state = {
  scenarios: [],
  scenarioId: "studio",
  scenario: null,
  compare: null,
  objective: "burden",
  mode: "committed",
  side: "baseline",
  capacityDrafts: {},
  lastOverrides: null,
  envy: { observer: null, target: null },
  enumScenario: "micro",
  enumeration: null,
  busy: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = Number(value);
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

function currency(value) {
  const symbol = state.scenario?.currency || "¥";
  return `${symbol}${fmt(value, 0)}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function packageName(pid) {
  const p = state.scenario?.packages?.find((x) => x.id === pid);
  return p ? p.name : pid;
}

function memberName(mid) {
  const m = state.scenario?.members?.find((x) => x.id === mid);
  return m ? m.name : mid;
}

function packageLabel(pid) {
  return `${pid} · ${packageName(pid)}`;
}

function activeAcceptances() {
  return state.compare?.acceptances || {};
}

function currentSideGroup() {
  if (!state.compare) return null;
  if (state.side === "adjusted" && state.compare.adjusted) return state.compare.adjusted;
  return state.compare.baseline;
}

function currentPlan() {
  const group = currentSideGroup();
  return group?.[state.mode]?.[state.objective] || null;
}

function setBusy(busy) {
  state.busy = busy;
  document.body.classList.toggle("loading", busy);
}

async function loadScenarioList() {
  const data = await api("/api/scenarios");
  state.scenarios = data.scenarios;
  renderScenarioList();
  const enumSelect = $("#enumScenario");
  enumSelect.innerHTML = ENUM_IDS.map((id) => {
    const s = state.scenarios.find((x) => x.id === id);
    return `<option value="${escapeHtml(id)}">${escapeHtml(s?.name || id)}</option>`;
  }).join("");
  enumSelect.value = state.enumScenario;
}

async function selectScenario(scenarioId) {
  state.scenarioId = scenarioId;
  state.objective = "burden";
  state.mode = "committed";
  state.side = "baseline";
  state.envy = { observer: null, target: null };
  const scenarioData = await api(`/api/scenario?id=${encodeURIComponent(scenarioId)}`);
  state.scenario = scenarioData.scenario;
  state.capacityDrafts = Object.fromEntries(
    state.scenario.members.map((m) => [m.id, Number(m.capacity)])
  );
  state.lastOverrides = null;
  renderScenarioList();
  renderScenarioChrome();
  await refreshCompare(null);
}

async function refreshCompare(capacityOverrides = state.lastOverrides) {
  setBusy(true);
  clearGlobalMessage();
  try {
    const data = await api("/api/compare", {
      method: "POST",
      body: {
        scenario: state.scenarioId,
        capacity_overrides: capacityOverrides || undefined,
      },
    });
    state.compare = data;
    state.lastOverrides = capacityOverrides || null;
    if (capacityOverrides) state.side = "adjusted";
    renderAll();
  } catch (error) {
    renderGlobalError(error.message);
  } finally {
    setBusy(false);
  }
}

async function refreshLedgerOnly() {
  const data = await api(`/api/ledger?scenario=${encodeURIComponent(state.scenarioId)}`);
  if (state.compare) {
    state.compare.acceptances = data.active;
    state.compare.ledger_records = data.records;
  }
  renderLedger();
  renderPlan();
}

function renderAll() {
  renderScenarioList();
  renderScenarioChrome();
  renderCapacityEditor();
  renderObjectiveControls();
  renderModeControls();
  renderKpisAndCards();
  renderCapacityDelta();
  renderPlan();
  renderLedger();
  renderAcceptForm();
}

function renderScenarioList() {
  const root = $("#scenarioList");
  if (!root) return;
  root.innerHTML = state.scenarios
    .map(
      (s) => `
      <button class="scenario-button" type="button" data-scenario="${escapeHtml(s.id)}"
        aria-pressed="${s.id === state.scenarioId}">
        <strong>${escapeHtml(s.name)}</strong>
        <span>${escapeHtml(s.id)} · ${s.member_count} 人 · ${s.package_count} 包</span>
      </button>`
    )
    .join("");
  const current = state.scenarios.find((s) => s.id === state.scenarioId);
  $("#scenarioDescription").textContent = current?.description || state.scenario?.description || "";
}

function renderScenarioChrome() {
  if (!state.scenario) return;
  $("#scenarioDescription").textContent = state.scenario.description;
  $("#solveMeta").textContent =
    `${state.scenario.id} · 完整 DFS 精确求解 · 同包块 ${currentPlan()?.optimality?.block_count ?? "—"} 个`;
  renderObjectiveControls();
  renderModeControls();
}

function renderObjectiveControls() {
  $$("[data-objective]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.objective === state.objective));
  });
}

function renderModeControls() {
  $$("[data-plan-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.planMode === state.mode));
  });
  $$("[data-capacity-side]").forEach((button) => {
    const side = button.dataset.capacitySide;
    button.setAttribute("aria-pressed", String(side === state.side));
    if (side === "adjusted") {
      button.disabled = !state.compare?.adjusted;
    }
  });
}

function renderCapacityEditor() {
  const root = $("#capacityEditor");
  if (!state.scenario) return;
  root.innerHTML = state.scenario.members
    .map((m, i) => {
      const value = state.capacityDrafts[m.id] ?? m.capacity;
      return `
        <label class="capacity-row">
          <span>
            <i class="legend-key" style="background:var(--series-${(i % 5) + 1})"></i>
            ${escapeHtml(m.name)}
            <span class="tiny muted">原 ${fmt(m.capacity, 0)}h</span>
          </span>
          <input type="number" min="0" step="1" data-capacity-input="${escapeHtml(m.id)}" value="${escapeHtml(value)}" />
        </label>`;
    })
    .join("");
  $$("[data-capacity-input]", root).forEach((input) => {
    input.addEventListener("input", () => {
      state.capacityDrafts[input.dataset.capacityInput] = Number(input.value);
    });
  });
}

function clearGlobalMessage() {
  $("#globalAlerts").innerHTML = "";
}

function renderGlobalError(message) {
  $("#globalAlerts").innerHTML = `<div class="alert critical"><strong>请求出错：</strong>${escapeHtml(message)}</div>`;
}

function conflictHtml(conflicts) {
  if (!conflicts?.length) return "";
  const items = conflicts
    .map((c) => {
      const pids = c.package_ids || [];
      const chips = pids
        .map((pid) => `<span class="pill bad conflict-package">${escapeHtml(packageLabel(pid))}</span>`)
        .join(" ");
      return `<li>${escapeHtml(c.message || c.code)}${chips ? `<div class="tag-row">${chips}</div>` : ""}</li>`;
    })
    .join("");
  return `
    <div class="alert critical">
      <strong>硬约束下无可行安排；以下是具体冲突工作包/集合。</strong>
      <ul>${items}</ul>
      <p class="tiny" style="margin-bottom:0">系统没有修改任何估时、资格或容量来“凑可行”。</p>
    </div>`;
}

function planConflictHtml(plan) {
  if (plan?.feasible) return "";
  return conflictHtml(plan?.conflicts || [{ message: "当前方案不可用。" }]);
}

function renderKpisAndCards() {
  const group = currentSideGroup();
  const kpiRoot = $("#kpiGrid");
  const cardsRoot = $("#objectiveCards");
  if (!group) {
    kpiRoot.innerHTML = "";
    cardsRoot.innerHTML = "";
    return;
  }

  const loss = group.commitment_loss?.[state.objective];
  const plan = group[state.mode][state.objective];
  const metric = plan?.metrics;
  const lossDelta = loss?.delta_primary;
  const lossClass = lossDelta === null || lossDelta === undefined ? "" : lossDelta > 0.001 ? "bad" : "good";
  const lossText = !loss
    ? "—"
    : loss.committed_feasible === false
      ? "承诺致无解"
      : `${lossDelta > 0 ? "+" : ""}${fmt(lossDelta, state.objective === "cost" ? 0 : 1)}`;

  kpiRoot.innerHTML = `
    <div class="kpi">
      <div class="label">最大个人负担</div>
      <div class="value">${metric ? fmt(metric.max_burden_hours) + "h" : "无解"}</div>
      <div class="sub">${metric ? `最高容量使用 ${fmt(metric.max_utilization_percent)}%` : "硬约束冲突"}</div>
    </div>
    <div class="kpi ${metric?.ef1 ? "good" : "bad"}">
      <div class="label">EF1 状态</div>
      <div class="value">${metric ? (metric.ef1 ? "满足" : fmt(metric.ef1_violation_count) + " 对") : "—"}</div>
      <div class="sub">${metric ? `最大移一项后残差 ${fmt(metric.max_ef1_residual_gap_hours)}h` : "无指标"}</div>
    </div>
    <div class="kpi">
      <div class="label">总成本</div>
      <div class="value">${metric ? currency(metric.total_cost) : "—"}</div>
      <div class="sub">个人成本单价 × 本人估时</div>
    </div>
    <div class="kpi ${lossClass}">
      <div class="label">承诺带来的目标损失</div>
      <div class="value">${escapeHtml(lossText)}</div>
      <div class="sub">${state.objective === "cost" ? "成本增量" : state.objective === "ef1" ? "EF1 违反对数/残差见卡片" : "最大负担增量"}</div>
    </div>
    <div class="kpi">
      <div class="label">搜索证明</div>
      <div class="value" style="font-size:18px;padding-top:7px">${plan?.optimality?.proven_optimal ? "最优 ✓" : "未证明"}</div>
      <div class="sub">${plan?.optimality?.feasible_leaves ?? 0} 个可行叶节点</div>
    </div>
  `;

  cardsRoot.innerHTML = OBJECTIVES.map((obj) => {
    const p = group[state.mode][obj.id];
    const m = p?.metrics;
    const l = group.commitment_loss?.[obj.id];
    let primary = "无解";
    let sub = "";
    if (m) {
      if (obj.id === "burden") {
        primary = `${fmt(m.max_burden_hours)}h`;
        sub = `成本 ${currency(m.total_cost)} · EF1 ${m.ef1 ? "✓" : m.ef1_violation_count + " 对违反"}`;
      } else if (obj.id === "ef1") {
        primary = m.ef1 ? "EF1 ✓" : `${m.ef1_violation_count} 对`;
        sub = `最大残差 ${fmt(m.max_ef1_residual_gap_hours)}h · 最大负担 ${fmt(m.max_burden_hours)}h`;
      } else {
        primary = currency(m.total_cost);
        sub = `最大负担 ${fmt(m.max_burden_hours)}h · EF1 ${m.ef1 ? "✓" : m.ef1_violation_count + " 对违反"}`;
      }
    }
    const delta = l?.delta_primary;
    const deltaHtml = delta === null || delta === undefined
      ? `<span class="pill bad">承诺冲突</span>`
      : Math.abs(delta) <= 0.001
        ? `<span class="pill">承诺损失 0</span>`
        : `<span class="pill warn">承诺 Δ ${delta > 0 ? "+" : ""}${fmt(delta, obj.id === "cost" ? 0 : 1)}</span>`;
    return `
      <button class="compare-objective-card" type="button" data-objective-card="${obj.id}"
        aria-pressed="${state.objective === obj.id}">
        <h3>${obj.label}</h3>
        <div class="metric-line"><span class="muted">${state.mode === "committed" ? "承诺内最优" : "自由最优"}</span><strong>${primary}</strong></div>
        <div class="tiny muted">${sub}</div>
        <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${deltaHtml}<span class="pill">${p?.optimality?.proven_optimal ? "精确解" : "不可行"}</span></div>
      </button>`;
  }).join("");

  $$("[data-objective-card]", cardsRoot).forEach((card) => {
    card.addEventListener("click", () => {
      state.objective = card.dataset.objectiveCard;
      renderAll();
    });
  });
}

function renderCapacityDelta() {
  const root = $("#capacityDelta");
  const delta = state.compare?.capacity_delta?.[state.mode]?.[state.objective];
  if (!delta) {
    root.innerHTML = `<span class="muted">尚未试调。</span>`;
    return;
  }
  if (delta.adjusted_feasible === false || delta.baseline_feasible === false) {
    root.innerHTML = `<span class="pill bad">某个容量情景无可行解，请查看冲突。</span>`;
    return;
  }
  const value = delta.delta_primary;
  const cls = value > 0.001 ? "delta-positive" : value < -0.001 ? "delta-negative" : "delta-zero";
  root.innerHTML = `
    <div class="alert ${value > 0.001 ? "warning" : "good"}" style="margin:0">
      <strong>容量试算：</strong>
      主目标变化 <span class="${cls}">${value > 0 ? "+" : ""}${fmt(value, state.objective === "cost" ? 0 : 1)}</span>；
      最大负担 ${fmt(delta.baseline_max_burden)}h → ${fmt(delta.adjusted_max_burden)}h，
      成本 ${currency(delta.baseline_cost)} → ${currency(delta.adjusted_cost)}。
      <button class="btn tiny-btn" type="button" id="viewAdjustedBtn">查看试算安排</button>
    </div>`;
  $("#viewAdjustedBtn")?.addEventListener("click", () => {
    state.side = "adjusted";
    renderModeControls();
    renderKpisAndCards();
    renderPlan();
  });
}

function constraintBadgesForPackage(pid) {
  const badges = [];
  const constraints = state.scenario?.constraints || {};
  (constraints.together || []).forEach((group) => {
    if (group.includes(pid)) {
      const others = group.filter((x) => x !== pid).map((x) => x).join(", ");
      badges.push(`<span class="tag constraint" title="必须同一人完成">🔗 同包${others ? "：" + escapeHtml(others) : ""}</span>`);
    }
  });
  (constraints.exclusive || []).forEach((group) => {
    if (group.includes(pid)) {
      const others = group.filter((x) => x !== pid).join(", ");
      badges.push(`<span class="tag constraint" title="不能由同一人承担">⛔ 互斥${others ? "：" + escapeHtml(others) : ""}</span>`);
    }
  });
  return badges.join("");
}

function renderBurdenChart(plan) {
  const root = $("#burdenChart");
  if (!plan?.feasible) {
    root.innerHTML = "";
    return;
  }
  const rows = plan.metrics.members;
  const scaleMax = Math.max(
    ...state.scenario.members.map((m) => Number(m.capacity)),
    ...rows.map((r) => Number(r.burden_hours)),
    1
  ) * 1.08;
  root.innerHTML = rows.map((r, i) => {
    const width = Math.max(1.5, (r.burden_hours / scaleMax) * 100);
    const capLeft = (r.capacity / scaleMax) * 100;
    const color = `var(--series-${(i % 5) + 1})`;
    return `
      <div class="bar-row">
        <div class="bar-label" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</div>
        <div class="bar-track" role="img" aria-label="${escapeHtml(r.name)}负担 ${r.burden_hours} 小时，容量 ${r.capacity} 小时">
          <div class="bar-fill" style="width:${width}%;background:${color}"></div>
          <div class="capacity-tick" data-capacity="${fmt(r.capacity, 0)}h" style="left:${capLeft}%"></div>
        </div>
        <div class="bar-value">${fmt(r.burden_hours)}h · ${fmt(r.utilization_percent)}%</div>
      </div>`;
  }).join("");
}

function renderPlan() {
  const board = $("#planBoard");
  const alertRoot = $("#planAlerts");
  const badges = $("#planBadges");
  const plan = currentPlan();
  const acceptances = activeAcceptances();

  if (!state.scenario || !state.compare) return;
  renderModeControls();

  const sideLabel = state.side === "adjusted" ? "试算容量" : "原容量";
  const modeLabel = state.mode === "committed" ? "遵守接受台账" : "忽略台账的自由对照";
  badges.textContent = `${sideLabel} · ${modeLabel}`;

  if (!plan?.feasible) {
    $("#burdenChart").innerHTML = "";
    alertRoot.innerHTML = planConflictHtml(plan);
    board.innerHTML = `
      <div class="alert warning">
        当前选择下没有可展示的分配看板。可切换到“自由重排对照”查看承诺前可行解，或在右侧处理冲突台账。
      </div>`;
    renderEnvySelects(null);
    $("#envyPanel").innerHTML = `<p class="muted">无可行方案，因此没有可解释的嫉妒关系。</p>`;
    return;
  }

  alertRoot.innerHTML = "";
  renderBurdenChart(plan);
  const ownerOf = plan.assignment;
  const blockForPid = {};
  (plan.blocks || []).forEach((b) => b.package_ids.forEach((pid) => { blockForPid[pid] = b; }));

  board.innerHTML = plan.metrics.members.map((member, memberIndex) => {
    const color = `var(--series-${(memberIndex % 5) + 1})`;
    const cards = member.package_ids.map((pid) => {
      const p = state.scenario.packages.find((x) => x.id === pid);
      const mid = member.member_id;
      const locked = acceptances[pid] === mid;
      const acceptedElsewhere = acceptances[pid] && acceptances[pid] !== mid;
      const block = blockForPid[pid];
      const dependencyForced = !locked && block?.is_commitment_locked;
      const required = (p.required_qualifications || [])
        .map((q) => `<span class="tag">${escapeHtml(q)}</span>`)
        .join("");
      const lockPill = locked
        ? `<span class="pill lock">🔒 已接受/承诺</span>`
        : dependencyForced
          ? `<span class="pill warn">🔗 依赖强制，未单独接受</span>`
          : acceptedElsewhere
            ? `<span class="pill bad">台账锁定他人</span>`
            : "";
      const action = locked
        ? `<span class="tiny muted">重算不会移动此项</span>`
        : `<button class="btn tiny-btn good" type="button" data-accept-pid="${escapeHtml(pid)}" data-accept-mid="${escapeHtml(mid)}">接受并锁定给${escapeHtml(member.name)}</button>`;
      return `
        <li class="package-card ${locked ? "locked" : ""}">
          <div class="package-title">${escapeHtml(p.name)} <span class="tiny muted mono">${escapeHtml(pid)}</span></div>
          <div class="package-stats">
            <span>本人估时 <strong>${fmt(p.hours[mid])}h</strong></span>
            <span>难度感受 <strong>${p.difficulty?.[mid] ?? "—"}/5</strong></span>
            <span>个人成本 <strong>${currency(p.costs[mid])}</strong></span>
          </div>
          <div class="tag-row">${required}${constraintBadgesForPackage(pid)}${lockPill}</div>
          <div class="package-actions">${action}</div>
        </li>`;
    }).join("") || `<li class="package-card muted small">未分配工作包</li>`;

    return `
      <article class="member-column">
        <div class="member-head" style="border-top:3px solid ${color}">
          <div>
            <div class="member-name">${escapeHtml(member.name)}</div>
            <div class="member-meta">${escapeHtml(state.scenario.members.find((m) => m.id === member.member_id)?.role || "")}</div>
          </div>
          <div class="member-burden">
            <div><strong>${fmt(member.burden_hours)} / ${fmt(member.capacity)}h</strong></div>
            <div class="tiny ${member.within_capacity ? "muted" : "delta-positive"}">${fmt(member.utilization_percent)}% · ${currency(member.personal_cost)}</div>
          </div>
        </div>
        <ul class="package-list">${cards}</ul>
      </article>`;
  }).join("");

  $$("[data-accept-pid]", board).forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api("/api/acceptances", {
          method: "POST",
          body: {
            scenario: state.scenarioId,
            package_id: button.dataset.acceptPid,
            member_id: button.dataset.acceptMid,
            source: "plan-button",
          },
        });
        await refreshCompare(state.lastOverrides);
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    });
  });

  renderEnvySelects(plan);
  renderEnvyPanel(plan);
}

function renderEnvySelects(plan) {
  const observerSelect = $("#observerSelect");
  const targetSelect = $("#targetSelect");
  const members = state.scenario?.members || [];
  if (!plan?.feasible || members.length < 2) {
    observerSelect.innerHTML = "";
    targetSelect.innerHTML = "";
    return;
  }

  const previousObserver = state.envy.observer;
  const previousTarget = state.envy.target;
  const violation = plan.metrics.envy_pairs.find((p) => !p.ef1_pair);
  const envious = plan.metrics.envy_pairs.find((p) => p.is_envious);
  const defaultObserver = violation?.observer_id || envious?.observer_id || previousObserver || members[0].id;
  let defaultTarget = violation?.target_id || envious?.target_id || previousTarget;
  if (!defaultTarget || defaultTarget === defaultObserver) {
    defaultTarget = members.find((m) => m.id !== defaultObserver)?.id;
  }
  if (!members.some((m) => m.id === previousObserver)) state.envy.observer = defaultObserver;
  if (!members.some((m) => m.id === previousTarget) || state.envy.target === state.envy.observer) {
    state.envy.target = defaultTarget;
  }

  observerSelect.innerHTML = members.map((m) =>
    `<option value="${escapeHtml(m.id)}" ${m.id === state.envy.observer ? "selected" : ""}>${escapeHtml(m.name)}</option>`
  ).join("");
  targetSelect.innerHTML = members.filter((m) => m.id !== state.envy.observer).map((m) =>
    `<option value="${escapeHtml(m.id)}" ${m.id === state.envy.target ? "selected" : ""}>${escapeHtml(m.name)}</option>`
  ).join("");

  observerSelect.onchange = () => {
    state.envy.observer = observerSelect.value;
    const firstOther = members.find((m) => m.id !== state.envy.observer)?.id;
    if (state.envy.target === state.envy.observer || !state.envy.target) state.envy.target = firstOther;
    renderPlan();
  };
  targetSelect.onchange = () => {
    state.envy.target = targetSelect.value;
    renderEnvyPanel(plan);
  };
}

function envyBarHtml(label, value, maxValue, color) {
  const width = Math.max(1.5, Math.min(100, (value / Math.max(maxValue, 0.1)) * 100));
  return `
    <div class="bar-row" style="grid-template-columns:86px 1fr 74px">
      <div class="bar-label">${escapeHtml(label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${width}%;background:${color}"></div></div>
      <div class="bar-value">${fmt(value)}h</div>
    </div>`;
}

function renderEnvyPanel(plan = currentPlan()) {
  const root = $("#envyPanel");
  if (!plan?.feasible) {
    root.innerHTML = `<p class="muted">无可行方案，因此没有可解释的嫉妒关系。</p>`;
    return;
  }
  const pair = plan.metrics.envy_pairs.find(
    (p) => p.observer_id === state.envy.observer && p.target_id === state.envy.target
  ) || plan.metrics.envy_pairs[0];
  if (!pair) {
    root.innerHTML = `<p class="muted">至少需要两名成员。</p>`;
    return;
  }

  const panelClass = !pair.is_envious ? "not-envious" : pair.ef1_pair ? "envious" : "ef1-bad";
  const maxScale = Math.max(pair.observer_self_burden_hours, pair.observer_values_target_bundle_hours, 1);
  const ownItems = pair.own_items.map((item) => `
    <div class="line-item">
      <span>${escapeHtml(item.package_name)} <span class="mono tiny muted">${escapeHtml(item.package_id)}</span></span>
      <span class="hours">${item.observer_difficulty ? `难度 ${escapeHtml(item.observer_difficulty)}/5 · ` : ""}${fmt(item.observer_estimated_hours)}h</span>
    </div>`).join("") || `<div class="tiny muted">空束：0h</div>`;
  const targetItems = pair.target_items.map((item) => `
    <div class="line-item">
      <span>${escapeHtml(item.package_name)} <span class="mono tiny muted">${escapeHtml(item.package_id)}</span></span>
      <span class="hours">${item.observer_difficulty ? `难度 ${escapeHtml(item.observer_difficulty)}/5 · ` : ""}${fmt(item.observer_estimated_hours)}h</span>
    </div>`).join("") || `<div class="tiny muted">空束：0h</div>`;
  const removals = pair.removal_candidates.map((candidate) => `
    <div class="line-item">
      <span>移走「${escapeHtml(candidate.package_name)}」</span>
      <span class="hours">残差 ${fmt(candidate.hypothetical_remaining_gap)}h ${candidate.eliminates_envy ? "✓" : "✕"}</span>
    </div>`).join("") || `<p class="tiny muted">自己的束为空，无需移走工作包。</p>`;

  root.innerHTML = `
    <div class="envy-summary ${panelClass}">
      <div>${escapeHtml(pair.explanation)}</div>
      <div class="tag-row">
        <span class="pill ${pair.is_envious ? "warn" : "good"}">${pair.is_envious ? "存在嫉妒" : "不嫉妒"}</span>
        <span class="pill ${pair.ef1_pair ? "good" : "bad"}">${pair.ef1_pair ? "满足 EF1（可移一项）" : "不满足 EF1"}</span>
      </div>
    </div>
    <div class="bar-chart" style="gap:9px;margin-top:4px">
      ${envyBarHtml(`${pair.observer_name}评自己`, pair.observer_self_burden_hours, maxScale, "var(--series-1)")}
      ${envyBarHtml(`${pair.observer_name}评${pair.target_name}`, pair.observer_values_target_bundle_hours, maxScale, "var(--series-2)")}
    </div>
    <div class="bundle-compare" style="margin-top:10px">
      <div class="bundle-box"><h4>${escapeHtml(pair.observer_name)}自己的束（按 ${escapeHtml(pair.observer_name)} 估时）</h4>${ownItems}</div>
      <div class="bundle-box"><h4>${escapeHtml(pair.target_name)}的束（仍按观察者估时）</h4>${targetItems}</div>
    </div>
    <h3>“移走一项”条件逐项试算</h3>
    ${removals}
  `;
}

function renderAcceptForm() {
  const packageSelect = $("#acceptPackage");
  const memberSelect = $("#acceptMember");
  if (!state.scenario) return;
  packageSelect.innerHTML = state.scenario.packages
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.id)} · ${escapeHtml(p.name)}</option>`)
    .join("");
  memberSelect.innerHTML = state.scenario.members
    .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)} · ${escapeHtml(m.role || "")}</option>`)
    .join("");
}

function renderLedger() {
  const root = $("#ledgerList");
  const records = state.compare?.ledger_records || [];
  const conflictPids = new Set(
    (currentSideGroup()?.committed?.burden?.conflicts || [])
      .flatMap((c) => c.package_ids || [])
  );
  if (!records.length) {
    root.innerHTML = `<p class="small muted">暂无接受记录。接受一个看板任务后，它会成为重算中的硬锁。</p>`;
    return;
  }
  root.innerHTML = records.slice().reverse().map((r) => `
    <div class="ledger-item ${conflictPids.has(r.package_id) ? "conflict" : ""}">
      <div><strong>${escapeHtml(memberName(r.member_id))}</strong> 接受 <strong>${escapeHtml(packageLabel(r.package_id))}</strong></div>
      ${r.note ? `<div class="small">${escapeHtml(r.note)}</div>` : ""}
      <div class="ledger-meta">${escapeHtml(r.accepted_at || "")} · 来源 ${escapeHtml(r.source || "unknown")} · ${conflictPids.has(r.package_id) ? "当前冲突集合" : "有效锁定"}</div>
    </div>
  `).join("");
}

async function runEnumeration() {
  const root = $("#enumerationResult");
  root.innerHTML = `<p class="muted">正在枚举并逐项检查…</p>`;
  setBusy(true);
  try {
    const data = await api(`/api/enumerate?scenario=${encodeURIComponent(state.enumScenario)}`);
    state.enumeration = data;
    renderEnumeration();
  } catch (error) {
    root.innerHTML = `<div class="alert critical">${escapeHtml(error.message)}</div>`;
  } finally {
    setBusy(false);
  }
}

function assignmentText(assignment) {
  return Object.entries(assignment || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([pid, mid]) => `${escapeHtml(pid)}→${escapeHtml(memberName(mid))}`)
    .join("，");
}

function renderEnumeration() {
  const data = state.enumeration;
  const root = $("#enumerationResult");
  if (!data) return;
  const allMatch = OBJECTIVES.every((obj) => data.optima[obj.id]?.matches_solver === true);
  const hasOptima = OBJECTIVES.some((obj) => data.optima[obj.id]);
  const objectiveRows = OBJECTIVES.map((obj) => {
    const optimum = data.optima[obj.id];
    return `
      <tr>
        <td><strong>${obj.label}</strong></td>
        <td class="num">${optimum ? escapeHtml(fmt(optimum.primary_value, obj.id === "cost" ? 0 : 2)) : "无可行解"}</td>
        <td>${optimum ? assignmentText(optimum.assignment) : "—"}</td>
        <td>${optimum?.matches_solver ? `<span class="pill good">一致 ✓</span>` : `<span class="pill bad">不一致</span>`}</td>
      </tr>`;
  }).join("");

  const detailRows = data.rows.slice(0, 100).map((row) => `
    <tr>
      <td class="num">${row.index}</td>
      <td>${assignmentText(row.assignment)}</td>
      <td>${row.feasible ? `<span class="pill good">可行</span>` : `<span class="pill bad">${escapeHtml((row.violation_codes || []).join(","))}</span>`}</td>
      <td class="num">${row.max_burden_hours ?? "—"}</td>
      <td class="num">${row.total_cost ?? "—"}</td>
      <td>${row.ef1 === undefined ? "—" : row.ef1 ? "✓" : `${row.ef1_violation_count} 对`}</td>
    </tr>
  `).join("");

  root.innerHTML = `
    <div class="kpi-grid" style="margin-top:14px">
      <div class="kpi"><div class="label">原始分配总数</div><div class="value">${data.total_assignments}</div><div class="sub">未经块压缩</div></div>
      <div class="kpi good"><div class="label">硬约束可行</div><div class="value">${data.feasible_count}</div><div class="sub">独立检查器计数</div></div>
      <div class="kpi bad"><div class="label">不可行</div><div class="value">${data.infeasible_count}</div><div class="sub">资格/容量/依赖/互斥</div></div>
      <div class="kpi ${allMatch ? "good" : "bad"}"><div class="label">求解器最优界</div><div class="value" style="font-size:20px;padding-top:8px">${!hasOptima ? "无可行解" : allMatch ? "全部匹配 ✓" : "存在偏差"}</div><div class="sub">${hasOptima ? "DFS key 与枚举 min key 对比" : "硬约束冲突已在求解页列出"}</div></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>目标</th><th class="num">枚举最优主值</th><th>枚举最优安排</th><th>与精确 DFS 核对</th></tr></thead>
        <tbody>${objectiveRows}</tbody>
      </table>
    </div>
    <details class="enum-details">
      <summary class="btn" style="display:inline-block;margin:10px 0">查看前 100 个原始枚举行</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="num">#</th><th>分配</th><th>状态</th><th class="num">最大负担</th><th class="num">成本</th><th>EF1</th></tr></thead>
          <tbody>${detailRows}</tbody>
        </table>
      </div>
    </details>
  `;
}

function bindEvents() {
  $("#scenarioList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-scenario]");
    if (button) selectScenario(button.dataset.scenario).catch((err) => renderGlobalError(err.message));
  });

  $$("[data-objective]").forEach((button) => {
    button.addEventListener("click", () => {
      state.objective = button.dataset.objective;
      renderObjectiveControls();
      renderKpisAndCards();
      renderPlan();
    });
  });

  $$("[data-plan-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.planMode;
      renderAll();
    });
  });

  $$("[data-capacity-side]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      state.side = button.dataset.capacitySide;
      renderModeControls();
      renderKpisAndCards();
      renderCapacityDelta();
      renderPlan();
    });
  });

  $("#applyCapacity").addEventListener("click", async () => {
    const overrides = {};
    for (const [mid, value] of Object.entries(state.capacityDrafts)) {
      const n = Number(value);
      if (Number.isFinite(n) && n >= 0) overrides[mid] = n;
    }
    await refreshCompare(overrides);
  });

  $("#resetCapacity").addEventListener("click", async () => {
    state.capacityDrafts = Object.fromEntries(
      state.scenario.members.map((m) => [m.id, Number(m.capacity)])
    );
    state.side = "baseline";
    state.lastOverrides = null;
    renderCapacityEditor();
    await refreshCompare(null);
  });

  $("#acceptForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {
      scenario: state.scenarioId,
      package_id: $("#acceptPackage").value,
      member_id: $("#acceptMember").value,
      note: $("#acceptNote").value,
      source: "manual-form",
    };
    try {
      await api("/api/acceptances", { method: "POST", body });
      $("#acceptNote").value = "";
      await refreshCompare(state.lastOverrides);
    } catch (error) {
      alert(error.message);
    }
  });

  $("#clearLedger").addEventListener("click", async () => {
    if (!confirm("清空本场景全部接受记录？这是演示管理操作；真实承诺不应被随意撤销。")) return;
    await api("/api/ledger/clear", { method: "POST", body: { scenario: state.scenarioId } });
    await refreshCompare(state.lastOverrides);
  });

  const resetScenarioLedger = async () => {
    await api("/api/ledger/reset", { method: "POST", body: { scenario: state.scenarioId } });
    await refreshCompare(state.lastOverrides);
  };
  $("#seedLedger").addEventListener("click", resetScenarioLedger);
  $("#resetLedgerTop").addEventListener("click", async () => {
    await api("/api/ledger/reset", { method: "POST", body: {} });
    await selectScenario(state.scenarioId);
  });

  $("#runEnumeration").addEventListener("click", runEnumeration);
  $("#enumScenario").addEventListener("change", (event) => {
    state.enumScenario = event.target.value;
    state.enumeration = null;
    $("#enumerationResult").innerHTML = `<p class="muted">已选择 ${escapeHtml(state.enumScenario)}，点击“运行枚举核对”。</p>`;
  });

  $("#themeToggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("allocation-theme", next); } catch { /* ignore */ }
  });
}

function initTheme() {
  let theme = null;
  try { theme = localStorage.getItem("allocation-theme"); } catch { /* ignore */ }
  if (!theme && window.matchMedia?.("(prefers-color-scheme: dark)").matches) theme = "dark";
  if (theme) document.documentElement.dataset.theme = theme;
}

async function init() {
  initTheme();
  bindEvents();
  try {
    await loadScenarioList();
    await selectScenario("studio");
    state.enumScenario = "micro";
    $("#enumScenario").value = "micro";
    await runEnumeration();
  } catch (error) {
    renderGlobalError(error.message);
  }
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
