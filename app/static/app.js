"use strict";
const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const labels = {
  MISSING_PAYMENT: "Missing payment",
  DUPLICATE_DIRECT_DEBIT: "Duplicate direct debit",
  RATE_MARGIN_BREACH: "Rate margin breach",
};
const statusLabels = {
  created: "Queued",
  ingesting: "Scanning input",
  proposing_mapping: "Proposing mapping",
  awaiting_confirmation: "Awaiting your confirmation",
  queued: "Mapping confirmed · queued",
  reconciling: "Reconciling",
  explaining: "Validating explanations",
  complete: "Run complete",
  input_blocked: "Input held",
  error: "Run failed",
};
const validatorLabels = {
  faithfulness: "Grounded values & IDs",
  answer_relevance: "Answer relevance",
  classification_in_set: "Allowed classification",
  plan_coherence: "Execution order",
  injection_scan: "Injection scan",
  pii_scan: "PII scan",
};
const activeStatuses = new Set([
  "created",
  "ingesting",
  "proposing_mapping",
  "queued",
  "reconciling",
  "explaining",
]);
let current = null,
  analytics = null,
  health = null,
  queue = "pass",
  mappingRendered = null,
  pollTimer = null,
  pollGeneration = 0;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The request is invalid. Check the supplied fields.",
    );
  return data;
}
const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body) });
function notice(message) {
  $("message").textContent = message;
  $("message").hidden = !message;
}
function switchView(view) {
  for (const name of ["desk", "audit", "settings"])
    $(name + "-view").hidden = name !== view;
  document
    .querySelectorAll(".nav-item")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.view === view),
    );
  if (view === "audit") renderAnalytics();
}
document
  .querySelectorAll("[data-view]")
  .forEach((button) =>
    button.addEventListener("click", () => switchView(button.dataset.view)),
  );
function openRun() {
  $("run-dialog").showModal();
}
$("new-run").addEventListener("click", openRun);
$("empty-start").addEventListener("click", openRun);
$("close-run").addEventListener("click", () => $("run-dialog").close());
$("close-evidence").addEventListener("click", () =>
  $("evidence-dialog").close(),
);
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("start-run");
  button.disabled = true;
  try {
    const body = {
      seed: Number($("seed").value),
      n_loans: Number($("n-loans").value),
      provider: $("provider").value,
      synthetic_data: true,
    };
    const files = ["servicing", "payments", "investor"].map((kind) => [
      kind,
      $("upload-" + kind).files[0],
    ]);
    if (files.some(([, file]) => file)) {
      if (files.some(([, file]) => !file))
        throw new Error("Choose all three synthetic CSV files.");
      if (files.some(([, file]) => file.size > 512000))
        throw new Error("Each CSV must be at most 512 KB.");
      body.files = Object.fromEntries(
        await Promise.all(
          files.map(async ([kind, file]) => [kind, await file.text()]),
        ),
      );
    }
    notice("");
    current = await post("/runs?background=true", body);
    mappingRendered = null;
    queue = "pass";
    $("search").value = "";
    $("run-dialog").close();
    switchView("desk");
    await selectRun(current.run_id);
  } catch (error) {
    notice(error.message);
    $("run-dialog").close();
  } finally {
    button.disabled = false;
  }
});

async function refreshRecent() {
  const runs = await api("/runs");
  $("run-count").textContent = runs.length;
  $("recent-runs").innerHTML = runs.length
    ? runs
        .map(
          (run) =>
            `<button class="recent-run ${current?.run_id === run.run_id ? "active" : ""}" data-run="${escape(run.run_id)}"><span>▤</span><span>${escape(run.run_id.slice(0, 8))}<small>${escape(statusLabels[run.status] || run.status)} · ${escape(run.provider)}</small></span></button>`,
        )
        .join("")
    : "<p>No runs yet</p>";
  $("recent-runs")
    .querySelectorAll("[data-run]")
    .forEach((button) =>
      button.addEventListener("click", () => {
        switchView("desk");
        selectRun(button.dataset.run).catch((error) => notice(error.message));
      }),
    );
  return runs;
}
async function selectRun(id) {
  clearTimeout(pollTimer);
  const generation = ++pollGeneration;
  async function refresh() {
    try {
      const [run, stats] = await Promise.all([
        api("/runs/" + id),
        api("/runs/" + id + "/analytics"),
      ]);
      if (generation !== pollGeneration) return;
      current = run;
      analytics = stats;
      localStorage.setItem("uc1-selected-run", id);
      renderRun();
      renderAnalytics();
      await refreshRecent();
      if (activeStatuses.has(run.status)) pollTimer = setTimeout(refresh, 1200);
    } catch (error) {
      if (generation === pollGeneration) notice(error.message);
    }
  }
  await refresh();
}

function renderRun() {
  if (!current) return;
  const r = current,
    afterEngine = ["explaining", "complete"].includes(r.status);
  $("run-title").textContent = "Run " + r.run_id.slice(0, 8);
  $("run-subtitle").textContent =
    `${r.provider === "ollama" ? "Local Qwen" : r.provider === "mock" ? "Mock templates" : "OpenAI"} · ${new Date(r.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`;
  $("status-badge").textContent = statusLabels[r.status] || r.status;
  $("status-badge").className =
    "badge " +
    (r.status === "complete"
      ? "green-bg"
      : ["input_blocked", "error"].includes(r.status)
        ? "red-bg"
        : "amber-bg");
  const stage = [
    "created",
    "ingesting",
    "proposing_mapping",
    "input_blocked",
  ].includes(r.status)
    ? 0
    : r.status === "awaiting_confirmation"
      ? 1
      : ["queued", "reconciling"].includes(r.status)
        ? 2
        : 3;
  document.querySelectorAll(".steps li").forEach((item, index) => {
    item.classList.toggle("active", index === stage);
    item.classList.toggle("done", index < stage || r.status === "complete");
  });
  $("metric-loans").textContent = r.files.servicing?.row_count ?? "—";
  $("metric-found").textContent = afterEngine
    ? r.engine_exceptions.length
    : "—";
  $("metric-pass").textContent = afterEngine ? r.remediation_log.length : "—";
  $("metric-held").textContent = afterEngine ? r.held_for_review.length : "—";
  $("pass-tab-count").textContent = r.remediation_log.length;
  $("held-tab-count").textContent = r.held_for_review.length;
  $("export").disabled = r.status !== "complete";
  $("outcome-caption").textContent =
    r.status === "explaining"
      ? `Validating exception ${r.progress.completed} of ${r.progress.total}. Engine findings are already available.`
      : "Engine findings and validated explanations, together.";
  $("mapping-panel").hidden = r.status !== "awaiting_confirmation";
  if (r.status === "awaiting_confirmation" && mappingRendered !== r.run_id)
    renderMapping();
  if (r.error) notice(r.error);
  else if (r.status === "input_blocked")
    notice(
      "Input scans blocked this run before any model call. " +
        Object.values(r.ingest_findings).flat().join(" · "),
    );
  else if (r.mapping_issues.length)
    notice("Detection coverage is reduced: " + r.mapping_issues.join(" · "));
  $("model-label").textContent =
    r.provider === "mock"
      ? "Mock templates · no model judgment"
      : r.provider === "ollama"
        ? "Qwen · local inference"
        : "OpenAI · configured provider";
  $("model-note").textContent = r.model;
  const means = analytics?.validator_means || {};
  $("validation-pulse").innerHTML = Object.keys(means).length
    ? Object.entries(validatorLabels)
        .map(
          ([key, label]) =>
            `<div class="pulse-row"><div><span>${escape(label)}</span><span>${Math.round((means[key] ?? 0) * 100)}%</span></div><div class="bar"><span class="${means[key] < 1 ? "warn" : ""}" style="width:${(means[key] ?? 0) * 100}%"></span></div></div>`,
        )
        .join("")
    : '<p class="muted">Scores appear after the first exception is validated.</p>';
  $("ground-truth").innerHTML = r.score
    ? `<strong>${Math.round(r.score.recall * 100)}<small>% recall</small></strong><span>${r.score.true_positives} true positives · ${r.score.false_positives} false positives · ${r.score.false_negatives} missed</span>`
    : "<strong>—</strong><span>" +
      (afterEngine
        ? "No answer key supplied for uploaded files."
        : "Recall against the generated answer key") +
      "</span>";
  renderExceptions();
  document.dispatchEvent(new CustomEvent("uc1:run-rendered", { detail: r }));
}

function renderMapping() {
  mappingRendered = current.run_id;
  $("mapping-reviewed").checked = false;
  $("confirm").disabled = true;
  $("mapping-errors").textContent = current.mapping_errors
    .map((error) => error.file_kind + ": " + error.message)
    .join(" · ");
  $("mapping-tables").innerHTML = Object.entries(current.files)
    .map(
      ([kind, file]) =>
        `<section class="mapping-table"><h3>${escape(file.filename)} <small>${file.row_count} records</small></h3><div class="mapping-grid heading"><span>SOURCE COLUMN</span><span>SAMPLE VALUES</span><span>MAPS TO</span></div>${file.headers.map((raw) => `<div class="mapping-grid"><code>${escape(raw)}</code><span class="samples">${escape(file.preview.map((row) => row[raw]).join(" · "))}</span><select aria-label="${escape(kind + " " + raw + " mapping")}" data-kind="${escape(kind)}" data-raw="${escape(raw)}"><option value="">Leave unmapped</option>${health.canonical_fields[kind].map((field) => `<option value="${escape(field)}" ${current.proposed_mapping[kind]?.[raw] === field ? "selected" : ""}>${escape(field)}</option>`).join("")}</select></div>`).join("")}</section>`,
    )
    .join("");
  $("mapping-tables")
    .querySelectorAll("select")
    .forEach((select) =>
      select.addEventListener("change", () => {
        $("mapping-reviewed").checked = false;
        $("confirm").disabled = true;
      }),
    );
}
$("mapping-reviewed").addEventListener("change", () => {
  $("confirm").disabled = !$("mapping-reviewed").checked;
});
$("confirm").addEventListener("click", async () => {
  $("confirm").disabled = true;
  const mapping = { servicing: {}, payments: {}, investor: {} };
  $("mapping-tables")
    .querySelectorAll("select")
    .forEach((select) => {
      if (select.value)
        mapping[select.dataset.kind][select.dataset.raw] = select.value;
    });
  try {
    notice("");
    await post("/runs/" + current.run_id + "/confirm?background=true", {
      mapping,
    });
    await selectRun(current.run_id);
  } catch (error) {
    notice(error.message);
    $("confirm").disabled = false;
  }
});
document.querySelectorAll("[data-queue]").forEach((button) =>
  button.addEventListener("click", () => {
    queue = button.dataset.queue;
    renderExceptions();
  }),
);
$("search").addEventListener("input", renderExceptions);

function renderExceptions() {
  document.querySelectorAll("[data-queue]").forEach((button) => {
    button.classList.toggle("active", button.dataset.queue === queue);
    button.setAttribute("aria-selected", button.dataset.queue === queue);
  });
  if (!current) return;
  const r = current,
    all = queue === "pass" ? r.remediation_log : r.held_for_review;
  const entries = all.filter((item) =>
    item.loan_id.toLowerCase().includes($("search").value.toLowerCase()),
  );
  if (entries.length) {
    $("exception-list").innerHTML = entries
      .map(
        (item) =>
          `<article class="exception-row"><div class="exception-top"><strong>${escape(item.loan_id)}</strong><span class="type-tag">${escape(labels[item.type] || item.type)}</span><span class="badge ${item.verdict === "PASS" ? "green-bg" : "amber-bg"}">${item.verdict === "PASS" ? "✓ Passed" : "Held"}</span></div><p>${escape(item.engine_detail)}</p>${
            item.verdict === "BLOCK"
              ? '<p class="held-note">AI explanation withheld. ' +
                escape(
                  Object.keys(item.findings)
                    .map((name) => name.replaceAll("_", " "))
                    .join(" · "),
                ) +
                ".</p>"
              : ""
          }<div class="exception-bottom"><span><span>${escape(item.owner)}</span><span>·</span><span>${escape(item.priority)} priority</span></span><button class="text-button evidence-button" data-ex="${escape(item.ex_id)}">${item.evidence.length} source rows ↗</button></div></article>`,
      )
      .join("");
    $("exception-list")
      .querySelectorAll("[data-ex]")
      .forEach((button) =>
        button.addEventListener("click", () => showEvidence(button.dataset.ex)),
      );
  } else if (all.length)
    $("exception-list").innerHTML =
      '<div class="filter-empty">No loans match your search.</div>';
  else {
    const busy = activeStatuses.has(r.status);
    let title = "No explanations in this queue",
      description =
        queue === "held"
          ? "No exceptions have been held for review."
          : "Passed explanations appear here once validation completes.";
    if (r.status === "awaiting_confirmation") {
      title = "Your mapping review comes first";
      description =
        "The graph is paused. Confirm the column mapping above to start deterministic reconciliation.";
    } else if (busy) {
      title =
        r.status === "explaining"
          ? "Checking every explanation"
          : "Preparing your reconciliation";
      description =
        r.status === "explaining"
          ? `${r.engine_exceptions.length} engine findings retained. ${r.progress.completed} of ${r.progress.total} explanations processed.`
          : "Input scans and mapping proposals are recorded as the run progresses.";
    } else if (r.status === "input_blocked") {
      title = "Source files need review";
      description =
        "An input scan failed. No model has consumed the data and reconciliation has not started.";
    } else if (r.status === "error") {
      title = "This run needs attention";
      description = r.error;
    } else if (r.status === "complete" && r.engine_exceptions.length === 0) {
      title = "No configured exception patterns found";
      description = r.mapping_issues.length
        ? "Some fields were not mapped. Review the coverage warnings before interpreting this result."
        : "The engine found none of the three supported patterns. This is not a completeness guarantee.";
    }
    $("exception-list").innerHTML =
      `<div class="empty-state"><div class="${busy ? "busy-dot" : "empty-icon"}">${busy ? "" : "✓"}</div><h3>${escape(title)}</h3><p>${escape(description)}</p></div>`;
  }
}
function showEvidence(exId) {
  const item = [...current.remediation_log, ...current.held_for_review].find(
    (row) => row.ex_id === exId,
  );
  if (!item) return;
  $("evidence-title").textContent = item.loan_id + " · " + labels[item.type];
  $("evidence-content").innerHTML =
    `<div class="engine-fact"><b>Deterministic finding</b><br>${escape(item.engine_detail)}</div>${item.rationale ? "<h3>AI explanation · passed configured checks</h3><p>" + escape(item.rationale) + "</p>" : '<p class="held-note">AI explanation withheld. Review the engine facts and original source records below.</p>'}<h3>Validation results</h3>${Object.entries(
      item.scores,
    )
      .map(
        ([name, score]) =>
          `<div class="score-detail"><span>${escape(name.replaceAll("_", " "))}</span><span>${Math.round(score * 100)}%</span></div>`,
      )
      .join("")}${Object.values(item.findings)
      .flat()
      .map((finding) => '<p class="finding">' + escape(finding) + "</p>")
      .join(
        "",
      )}<h3>Verbatim source records</h3>${item.evidence.map((row) => `<h3>${escape(row.file.split("/").pop())} · line ${row.row_number}</h3><pre>${escape(row.raw_text)}</pre><details><summary class="muted">Column names and values</summary><pre>${escape(JSON.stringify(row.raw, null, 2))}</pre></details>`).join("")}`;
  $("evidence-dialog").showModal();
}
function renderAnalytics() {
  if (!analytics) return;
  const a = analytics;
  $("trace-label").textContent =
    {
      local: "Local JSONL audit",
      live: "Direct HTTP + local audit",
      "sdk-local": "SDK → local capture",
      "sdk-live": "Disseqt SDK + local audit",
    }[current.trace_mode] || "Trace transport";
  const duration = a.active_duration_ms / 1000;
  $("analytics-summary").innerHTML =
    `<div><strong>${duration.toFixed(1)}s</strong><span>Active processing · approval wait excluded</span></div><div><strong>${a.model_calls.length}</strong><span>Model operations · ${escape(current.provider)}</span></div><div><strong>${a.token_total === null ? "Unknown" : a.token_total.toLocaleString()}</strong><span>Recorded model tokens</span></div><div><strong>${a.estimated_api_cost_usd === null ? "Unknown" : "$" + a.estimated_api_cost_usd.toFixed(2)}</strong><span>${escape(a.cost_note)}</span></div>`;
  const max = Math.max(1, ...a.span_timeline.map((span) => span.duration_ms));
  $("timeline").className = "timeline";
  $("timeline").innerHTML = a.span_timeline
    .map(
      (span, index) =>
        `<div class="timeline-row"><span>${String(index + 1).padStart(2, "0")}</span><div>${escape(span.name)} ${span.status === "error" ? '<span class="amber">· failed</span>' : ""}</div><small>${escape(span.kind.replace("_EXEC", "").toLowerCase())}</small><div class="timeline-bar"><div style="width:${Math.max(1, (span.duration_ms / max) * 100)}%"></div></div><span>${span.duration_ms < 1000 ? span.duration_ms.toFixed(0) + " ms" : (span.duration_ms / 1000).toFixed(1) + " s"}</span></div>`,
    )
    .join("");
  $("baseline-drift").textContent = a.drift
    ? `Difference from “${a.baseline.label}”: ${(a.drift.active_duration_ms / 60000).toFixed(2)} minutes of processing; ${a.drift.exception_count >= 0 ? "+" : ""}${a.drift.exception_count} detected exceptions. Comparability depends on using the same loan book.`
    : "No baseline recorded.";
  if (a.delivery_errors.length)
    notice(
      "Some Disseqt deliveries failed. Full local traces have been retained.",
    );
}
$("baseline-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const form = new FormData(event.target);
    await post("/baseline", {
      active_duration_ms: Number(form.get("minutes")) * 60000,
      exception_count: Number(form.get("exceptions")),
    });
    if (current) await selectRun(current.run_id);
    notice("Manual baseline recorded for this server session.");
  } catch (error) {
    notice(error.message);
  }
});
$("export").addEventListener("click", () => {
  if (!current) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(current, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "reconciliation-" + current.run_id + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function init() {
  try {
    health = await api("/health");
    $("qwen-id").textContent = health.ollama_model;
    $("provider").value = health.default_provider;
    $("provider").querySelector('[value="openai"]').disabled =
      !health.openai_configured;
    $("openai-state").textContent = health.openai_configured
      ? "Key configured · explicit selection"
      : "Not configured";
    $("disseqt-state").textContent =
      health.trace_mode === "sdk"
        ? "Official SDK configured"
        : health.trace_mode === "live"
          ? "Direct HTTP configured"
          : "Local traces active";
    const runs = await refreshRecent();
    const previous = localStorage.getItem("uc1-selected-run");
    if (runs.length)
      await selectRun(
        runs.some((run) => run.run_id === previous) ? previous : runs[0].run_id,
      );
  } catch (error) {
    notice("Cannot reach the local API: " + error.message);
  }
}
init();
