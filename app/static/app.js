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
  MISSING_PAYMENT: "Payment not recorded",
  DUPLICATE_DIRECT_DEBIT: "Possible repeated payment",
  RATE_MARGIN_BREACH: "Higher rate margin recorded",
};
const fields = {
  loan_id: "Account number",
  period: "Payment month",
  scheduled_amount: "Payment due",
  contractual_margin: "Agreed rate margin (%)",
  posting_id: "Payment reference",
  received_amount: "Payment recorded",
  payment_method: "Payment method",
  reported_amount: "Cash in lender report",
  charged_margin: "Recorded rate margin (%)",
};
const fileLabels = {
  servicing: "Payment schedule",
  payments: "Payment record",
  investor: "Lender report",
};
const fileKinds = {
  "servicing_extract.csv": "servicing",
  "payments_file.csv": "payments",
  "investor_report.csv": "investor",
};
const statusLabels = {
  created: "Getting ready",
  ingesting: "Reading files",
  proposing_mapping: "Reading file labels",
  awaiting_confirmation: "Check the file labels",
  queued: "Ready to compare",
  reconciling: "Comparing payments",
  explaining: "Preparing explanations",
  complete: "Check complete",
  input_blocked: "Files need attention",
  error: "Check stopped",
};
const validatorLabels = {
  faithfulness: "Numbers and account references",
  answer_relevance: "Relevant explanation",
  classification_in_set: "Recognised issue type",
  plan_coherence: "Steps in the right order",
  injection_scan: "Input instruction scan",
  pii_scan: "Personal information scan",
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
  queue = "all",
  mappingRendered = null,
  pollTimer = null,
  pollGeneration = 0,
  selectedAccount = "",
  examples = [];

const currencies = { GBP: "£", EUR: "€", USD: "$" };
let displayCurrency = "GBP";
try {
  const saved = localStorage.getItem("uc1-display-currency");
  if (Object.hasOwn(currencies, saved)) displayCurrency = saved;
} catch {}

// The source files do not specify currency. This is a display label, not FX.
// Keep exact decimal strings; floating point is only used for chart proportions.
function money(value) {
  if (value == null) return "—";
  const text = String(value).trim(),
    negative = text.startsWith("-"),
    [whole, fraction = "00"] = text.replace(/^[+-]/, "").split(".");
  return `${negative ? "−" : text.startsWith("+") ? "+" : ""}${currencies[displayCurrency]}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction.padEnd(2, "0")}`;
}
function renderCurrency() {
  $("currency-select").value = displayCurrency;
  $("currency-note").textContent =
    `Amounts labelled in ${displayCurrency} (${currencies[displayCurrency]}). Choose the currency used in your files; changing this label does not convert amounts. Received amounts include reversals.`;
}
renderCurrency();
$("currency-select").addEventListener("change", () => {
  const selected = $("currency-select").value;
  if (!Object.hasOwn(currencies, selected)) return;
  displayCurrency = selected;
  try {
    localStorage.setItem("uc1-display-currency", displayCurrency);
  } catch {}
  renderCurrency();
  renderPaymentSummary();
  renderExceptions();
});
function month(value) {
  return /^\d{4}-\d{2}$/.test(value || "")
    ? new Date(value + "-01T00:00:00Z").toLocaleDateString(undefined, {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      })
    : "Month not available";
}
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
        : "Check the supplied fields and try again.",
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
  for (const name of ["desk", "examples", "audit", "settings"])
    $(name + "-view").hidden = name !== view;
  document
    .querySelectorAll(".nav-item")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.view === view),
    );
  $("view-name").textContent = {
    desk: "Payment overview",
    examples: "Example files",
    audit: "Check details",
    settings: "Connections",
  }[view];
  if (view === "audit") renderAnalytics();
}
document
  .querySelectorAll("[data-view]")
  .forEach((button) =>
    button.addEventListener("click", () => switchView(button.dataset.view)),
  );

function sourceMode() {
  return document.querySelector('[name="source"]:checked').value;
}
function renderSourceOptions() {
  const upload = sourceMode() === "upload";
  $("upload-source").hidden = !upload;
  $("example-source").hidden = upload;
  const generated = !upload && !$("example-select").value;
  $("generated-options").hidden = !generated;
  $("seed").disabled = $("n-loans").disabled = !generated;
  const example = examples.find(
    (item) => item.id === $("example-select").value,
  );
  $("example-description").textContent =
    example?.description ||
    "Includes missing payments, repeated debits and differences in rate margins.";
  $("provider-help").textContent =
    $("provider").value === "mock"
      ? "Quick practice uses fixed explanations. The same payment calculations and file checks still run."
      : "AI explanations may take a few minutes. You will check the file labels before payment comparisons begin.";
}
function openRun(exampleId = "") {
  $("run-form").reset();
  $("provider").value = health?.default_provider || "mock";
  $("example-select").value = typeof exampleId === "string" ? exampleId : "";
  $("run-form-error").hidden = true;
  renderSourceOptions();
  $("run-dialog").showModal();
}
$("new-run").addEventListener("click", () => openRun());
$("empty-start").addEventListener("click", () => switchView("examples"));
$("close-run").addEventListener("click", () => $("run-dialog").close());
$("close-evidence").addEventListener("click", () =>
  $("evidence-dialog").close(),
);
document
  .querySelectorAll('[name="source"]')
  .forEach((radio) => radio.addEventListener("change", renderSourceOptions));
$("example-select").addEventListener("change", renderSourceOptions);
$("provider").addEventListener("change", renderSourceOptions);
$("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("start-run").disabled = true;
  $("run-form-error").hidden = true;
  try {
    const body = { provider: $("provider").value, synthetic_data: true };
    if (sourceMode() === "upload") {
      const files = ["servicing", "payments", "investor"].map((kind) => [
        kind,
        $("upload-" + kind).files[0],
      ]);
      if (files.some(([, file]) => !file))
        throw new Error(
          "Add all three CSV files: the payment schedule, payment record and lender report.",
        );
      if (files.some(([, file]) => file.size > 512000))
        throw new Error("Each CSV must be at most 512 KB.");
      body.files = Object.fromEntries(
        await Promise.all(
          files.map(async ([kind, file]) => [kind, await file.text()]),
        ),
      );
    } else if ($("example-select").value) {
      body.files = (
        await api("/examples/" + encodeURIComponent($("example-select").value))
      ).files;
    } else {
      body.seed = Number($("seed").value);
      body.n_loans = Number($("n-loans").value);
    }
    notice("");
    const started = await post("/runs?background=true", body);
    mappingRendered = null;
    queue = "all";
    selectedAccount = "";
    $("search").value = "";
    $("run-dialog").close();
    switchView("desk");
    await selectRun(started.run_id);
  } catch (error) {
    $("run-form-error").textContent = error.message;
    $("run-form-error").hidden = false;
  } finally {
    $("start-run").disabled = false;
  }
});

function renderExamples() {
  $("example-select").innerHTML =
    '<option value="">Monthly sample · 40 accounts</option>' +
    examples
      .map(
        (entry) =>
          `<option value="${escape(entry.id)}">${escape(entry.title)}</option>`,
      )
      .join("");
  $("example-cards").innerHTML =
    examples
      .map(
        (entry, index) =>
          `<article class="panel example-card"><span class="eyebrow">EXAMPLE ${String(index + 1).padStart(2, "0")} · 3 CSV FILES</span><h3>${escape(entry.title)}</h3><p>${escape(entry.description)}</p><p class="example-note">${escape(entry.expected_note)}</p><div class="example-actions"><button class="primary" data-example="${escape(entry.id)}">Use these files →</button><a href="/examples/${encodeURIComponent(entry.id)}/download" download>Download CSV pack ↓</a></div></article>`,
      )
      .join("") ||
    '<p class="chart-empty">Example packs are not available yet. The monthly sample is available in Check payment files.</p>';
  $("example-cards")
    .querySelectorAll("[data-example]")
    .forEach((button) =>
      button.addEventListener("click", () => openRun(button.dataset.example)),
    );
}
async function refreshRecent() {
  const runs = await api("/runs");
  $("run-count").textContent = runs.length;
  $("recent-runs").innerHTML = runs.length
    ? runs
        .map(
          (run) =>
            `<button class="recent-run ${current?.run_id === run.run_id ? "active" : ""}" data-run="${escape(run.run_id)}"><span aria-hidden="true">◴</span><span>Check ${escape(run.run_id.slice(0, 6))}<small>${escape(statusLabels[run.status] || run.status)}</small></span></button>`,
        )
        .join("")
    : "<p>Your checks will appear here.</p>";
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
  if (current?.run_id !== id) {
    selectedAccount = "";
    $("search").value = "";
    queue = "all";
  }
  async function refresh() {
    try {
      const [run, stats] = await Promise.all([
        api("/runs/" + id),
        api("/runs/" + id + "/analytics"),
      ]);
      if (generation !== pollGeneration) return;
      current = run;
      analytics = stats;
      try {
        localStorage.setItem("uc1-selected-run", id);
      } catch (_) {
        /* Optional browser preference. */
      }
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
  const r = current;
  $("run-title").textContent = "Check " + r.run_id.slice(0, 8);
  $("run-subtitle").textContent =
    (r.provider === "ollama"
      ? "Local AI explanations"
      : r.provider === "mock"
        ? "Practice mode · fixed explanations"
        : "OpenAI explanations") +
    " · " +
    new Date(r.created_at).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  $("status-badge").textContent = statusLabels[r.status] || r.status;
  $("status-badge").className =
    "badge " +
    (r.status === "complete"
      ? "green-bg"
      : ["error", "input_blocked"].includes(r.status)
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
  $("mapping-panel").hidden = r.status !== "awaiting_confirmation";
  if (r.status === "awaiting_confirmation" && mappingRendered !== r.run_id)
    renderMapping();
  $("export").disabled = r.status !== "complete";
  if (r.error)
    notice(
      "This check stopped. Review the file labels and values. More detail is available in the local audit.",
    );
  else if (r.status === "input_blocked")
    notice(
      "The input checks found content needing attention. Use invented sample accounts and check the files before trying again.",
    );
  else if (r.mapping_issues.length)
    notice(
      "Some file columns were not matched, so parts of the payment check could not run. Start a new check and confirm all required labels before relying on these results.",
    );
  else notice("");
  $("model-label").textContent =
    r.provider === "mock"
      ? "Practice mode · fixed explanations"
      : "Selected explanation service";
  $("model-note").textContent = r.model;
  renderPaymentSummary();
  renderExceptions();
  document.dispatchEvent(new CustomEvent("uc1:run-rendered", { detail: r }));
}

function displaySummary() {
  const s = current?.payment_summary;
  if (!s?.available) return null;
  if (!selectedAccount) return s;
  const account = s.accounts.find((item) => item.loan_id === selectedAccount);
  if (!account) return s;
  return {
    ...account,
    available: true,
    accounts: [account],
    account_count: 1,
    accounts_with_findings: account.issue_types.length ? 1 : 0,
    cash_counts: {
      matched: account.cash_status === "matched" ? 1 : 0,
      under: account.cash_status === "under" ? 1 : 0,
      over: account.cash_status === "over" ? 1 : 0,
    },
    margin_checked_accounts: account.charged_margin === null ? 0 : 1,
  };
}
function renderPaymentSummary() {
  document.dispatchEvent(new Event("uc1:scope-changed"));
  const full = current?.payment_summary,
    s = displaySummary();
  const accounts = full?.accounts || [];
  const options =
    '<option value="">All sample accounts' +
    (accounts.length ? ` (${accounts.length})` : "") +
    "</option>" +
    accounts
      .map(
        (account) =>
          `<option value="${escape(account.loan_id)}">${escape(account.loan_id)}</option>`,
      )
      .join("");
  if ($("account-select").innerHTML !== options)
    $("account-select").innerHTML = options;
  $("account-select").value = selectedAccount || "";
  $("account-select").disabled = !accounts.length;
  $("summary-unavailable").hidden = Boolean(s);
  if (!s) {
    $("summary-unavailable").textContent =
      full?.reason ||
      (current?.status === "complete"
        ? "This older check has no payment summary. Start a new check to see the payment charts."
        : "Payment figures appear after you confirm the file labels.");
    for (const id of [
      "metric-due",
      "metric-paid",
      "metric-shortfall",
      "metric-accounts",
      "chart-shortfall",
      "chart-excess",
      "donut-total",
    ])
      $(id).textContent = "—";
    $("month-label").textContent = "Payment month not confirmed";
    $("payment-bars").innerHTML =
      '<p class="chart-empty">No confirmed payment figures to display.</p>';
    $("payment-donut").style.background = "#edf1e7";
    $("payment-donut").setAttribute(
      "aria-label",
      "No confirmed payment figures to display",
    );
    $("payment-legend").innerHTML =
      '<p class="muted">Waiting for confirmed figures.</p>';
    $("account-table").innerHTML =
      '<p class="chart-empty">Account amounts are not available for this check.</p>';
    $("account-table-count").textContent = "";
    return;
  }
  $("month-label").textContent = s.period ? month(s.period) : "No account rows";
  if (s.margin_checked_accounts < s.account_count) {
    $("summary-unavailable").hidden = false;
    $("summary-unavailable").textContent =
      `Rate margins could be compared for ${s.margin_checked_accounts} of ${s.account_count} accounts shown. Some accounts have no matching row in the lender report.`;
  }
  $("metric-due").textContent = money(s.scheduled);
  $("metric-paid").textContent = money(s.received);
  $("metric-shortfall").textContent = money(s.shortfall);
  $("metric-accounts").textContent = s.accounts_with_findings;
  $("metric-accounts-note").textContent =
    `Of ${s.account_count} ${s.account_count === 1 ? "account" : "accounts"} shown · three checks`;
  $("chart-shortfall").textContent = money(s.shortfall);
  $("chart-excess").textContent = money(s.excess);
  const scale = Math.max(
    Math.abs(Number(s.scheduled)),
    Math.abs(Number(s.received)),
    1,
  );
  const difference = Number(s.net_difference);
  const differenceText =
    difference === 0
      ? "The total received matches the total due."
      : `${money(String(s.net_difference).replace(/^-/, ""))} ${difference < 0 ? "less" : "more"} recorded than due${selectedAccount ? " on this account" : " overall"}.`;
  $("payment-bars").innerHTML =
    [
      { label: "Payment due", value: s.scheduled, css: "due" },
      { label: "Payment recorded", value: s.received, css: "paid" },
    ]
      .map(
        (bar) =>
          `<div class="payment-bar-row ${bar.css}"><div><span>${bar.label}</span><b>${money(bar.value)}</b></div><div class="payment-bar-track" role="img" aria-label="${bar.label}: ${money(bar.value)} ${displayCurrency}"><span style="width:${(Math.abs(Number(bar.value)) / scale) * 100}%"></span></div></div>`,
      )
      .join("") +
    `<p class="chart-difference">${differenceText}${Number(s.received) < 0 ? " Net payments are negative because of reversals." : ""}</p>`;
  const colors = ["#7ea989", "#cda45e", "#9a8ab8"],
    names = ["Matches amount due", "Less received", "More received"],
    values = [s.cash_counts.matched, s.cash_counts.under, s.cash_counts.over];
  const first = s.account_count ? (values[0] / s.account_count) * 100 : 0,
    second = s.account_count
      ? ((values[0] + values[1]) / s.account_count) * 100
      : 0;
  $("payment-donut").style.background = s.account_count
    ? `conic-gradient(${colors[0]} 0% ${first}%,${colors[1]} ${first}% ${second}%,${colors[2]} ${second}% 100%)`
    : "#edf1e7";
  $("payment-donut").setAttribute(
    "aria-label",
    values
      .map((value, index) => `${value} accounts: ${names[index].toLowerCase()}`)
      .join("; "),
  );
  $("donut-total").textContent = s.account_count;
  $("payment-legend").innerHTML = values
    .map(
      (value, index) =>
        `<div class="legend-item"><i style="background:${colors[index]}"></i><span>${names[index]}</span><b>${value}</b></div>`,
    )
    .join("");
  $("account-table-count").textContent = `(${s.accounts.length})`;
  $("account-table").innerHTML =
    `<table><thead><tr><th>Sample account</th><th class="num">Due</th><th class="num">Received</th><th>Payment comparison</th></tr></thead><tbody>${s.accounts.map((account) => `<tr><td><button class="text-button" data-account="${escape(account.loan_id)}">${escape(account.loan_id)}</button></td><td class="num">${money(account.scheduled)}</td><td class="num">${money(account.received)}</td><td><span class="cash-label ${account.cash_status}">${{ matched: "Amount matches", under: "Less received", over: "More received" }[account.cash_status]}</span></td></tr>`).join("")}</tbody></table>`;
  $("account-table")
    .querySelectorAll("[data-account]")
    .forEach((button) =>
      button.addEventListener("click", () => {
        selectedAccount = button.dataset.account;
        $("search").value = "";
        renderPaymentSummary();
        renderExceptions();
        $("account-select").focus();
      }),
    );
}
$("account-select").addEventListener("change", () => {
  selectedAccount = $("account-select").value;
  $("search").value = "";
  renderPaymentSummary();
  renderExceptions();
});

function renderMapping() {
  mappingRendered = current.run_id;
  $("mapping-reviewed").checked = false;
  $("confirm").disabled = true;
  $("mapping-errors").textContent = current.mapping_errors.length
    ? "Some labels could not be suggested. Choose their meanings in the dropdowns below."
    : "";
  $("mapping-tables").innerHTML = Object.entries(current.files)
    .map(
      ([kind, file]) =>
        `<section class="mapping-table"><h3>${fileLabels[kind]}<small>${escape(file.filename)} · ${file.row_count} rows</small></h3><div class="mapping-grid heading"><span>LABEL IN YOUR FILE</span><span>EXAMPLE VALUES</span><span>THIS MEANS</span></div>${file.headers.map((raw) => `<div class="mapping-grid"><code>${escape(raw)}</code><span class="samples">${escape(file.preview.map((row) => row[raw]).join(" · "))}</span><select aria-label="${escape(kind + " " + raw + " mapping")}" data-kind="${kind}" data-raw="${escape(raw)}"><option value="">Choose a meaning…</option>${health.canonical_fields[kind].map((field) => `<option value="${field}" ${current.proposed_mapping[kind]?.[raw] === field ? "selected" : ""}>${escape(fields[field] || field)}</option>`).join("")}</select></div>`).join("")}</section>`,
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
function explanationFor(id) {
  return [
    ...(current?.remediation_log || []),
    ...(current?.held_for_review || []),
  ].find((item) => item.ex_id === id);
}
function accountFor(id) {
  return current?.payment_summary?.accounts?.find(
    (account) => account.loan_id === id,
  );
}
function describe(item) {
  const a = accountFor(item.loan_id),
    type = item.ex_type;
  if (!a)
    return {
      title: labels[type],
      body: "The records triggered this check. Some payment figures are unavailable; review the original file details.",
      chips: [],
      next: "Check the file labels and original records before drawing a conclusion.",
    };
  if (type === "MISSING_PAYMENT")
    return {
      title: a.posting_count
        ? "Payments were recorded, but the net amount is zero."
        : "No payment is recorded for this month.",
      body: `${money(a.scheduled)} was due for ${month(a.period)}. ${a.posting_count ? `The payment entries add up to ${money(a.received)} after reversals.` : "There is no payment entry for this account in the supplied file."}`,
      chips: [`Due ${money(a.scheduled)}`, `Recorded ${money(a.received)}`],
      next: "Compare the payment record with the schedule for this account and month. The supplied files may not reflect later payments.",
    };
  if (type === "DUPLICATE_DIRECT_DEBIT")
    return {
      title: "A payment may have been collected more than once.",
      body: `${a.direct_debit_count} direct-debit entries total ${money(a.direct_debit_total)}, against a scheduled payment of ${money(a.scheduled)}. This matches the repeated-payment pattern.`,
      chips: [
        `Due ${money(a.scheduled)}`,
        `Direct debits ${money(a.direct_debit_total)}`,
      ],
      next: "Check the payment references and whether each collection was intended. These files cannot establish whether the extra debit was authorised.",
    };
  return {
    title: "The recorded rate margin is higher than agreed.",
    body: `The lender report shows ${a.charged_margin}% while the payment schedule shows an agreed margin of ${a.contractual_margin}%.`,
    chips: [`Agreed ${a.contractual_margin}%`, `Recorded ${a.charged_margin}%`],
    next: "Compare the margin in the lender report with the agreement. This margin is one part of a rate, not the full interest rate or APR. The files do not show a monetary overcharge.",
  };
}
function renderExceptions() {
  document.querySelectorAll("[data-queue]").forEach((button) => {
    button.classList.toggle("active", button.dataset.queue === queue);
    button.setAttribute("aria-selected", button.dataset.queue === queue);
  });
  if (!current) return;
  const r = current;
  const scoped = r.engine_exceptions.filter(
    (item) => !selectedAccount || item.loan_id === selectedAccount,
  );
  $("all-tab-count").textContent = scoped.length;
  $("payments-tab-count").textContent = scoped.filter(
    (item) => item.ex_type !== "RATE_MARGIN_BREACH",
  ).length;
  $("rates-tab-count").textContent = scoped.filter(
    (item) => item.ex_type === "RATE_MARGIN_BREACH",
  ).length;
  const entries = scoped.filter(
    (item) =>
      (queue === "all" ||
        (queue === "rates") === (item.ex_type === "RATE_MARGIN_BREACH")) &&
      item.loan_id.toLowerCase().includes($("search").value.toLowerCase()),
  );
  $("outcome-caption").textContent =
    r.status === "explaining"
      ? `The figures are ready. Extra explanations: ${r.progress.completed} of ${r.progress.total} prepared.`
      : scoped.length
        ? `${scoped.length} ${scoped.length === 1 ? "item" : "items"} across ${new Set(scoped.map((item) => item.loan_id)).size} ${selectedAccount ? "selected account" : "sample accounts"}. Select an item to see the figures behind it.`
        : "We check for unrecorded payments, repeated debit patterns and higher rate margins.";
  if (entries.length) {
    $("exception-list").innerHTML = entries
      .map((item) => {
        const info = describe(item);
        return `<article class="exception-row"><span class="issue-icon ${item.ex_type === "RATE_MARGIN_BREACH" ? "rate" : ""}" aria-hidden="true">${item.ex_type === "RATE_MARGIN_BREACH" ? "%" : item.ex_type === "MISSING_PAYMENT" ? "−" : "↺"}</span><div class="issue-main"><span class="issue-kicker">SAMPLE ACCOUNT ${escape(item.loan_id)}</span><h3>${escape(info.title)}</h3><p>${escape(info.body)}</p><div class="issue-chips">${info.chips.map((chip) => `<span>${escape(chip)}</span>`).join("")}</div></div><button class="secondary evidence-button" data-ex="${escape(item.ex_id)}">See details →</button></article>`;
      })
      .join("");
    $("exception-list")
      .querySelectorAll("[data-ex]")
      .forEach((button) =>
        button.addEventListener("click", () => showEvidence(button.dataset.ex)),
      );
  } else {
    const busy = activeStatuses.has(r.status);
    let title = "No items in this view",
      copy = "Try another account or clear the search to see other results.";
    if (r.status === "awaiting_confirmation") {
      title = "Check the file labels first";
      copy =
        "Confirm that each column has the right meaning above. Payment comparisons start only after your confirmation.";
    } else if (busy) {
      title = "Your files are being checked";
      copy =
        "This page updates automatically. Local AI may take a few minutes to read headings and prepare explanations.";
    } else if (["input_blocked", "error"].includes(r.status)) {
      title = "These files need a closer look";
      copy =
        "See the message above. The check could not finish with the supplied files.";
    } else if (
      r.status === "complete" &&
      !scoped.length &&
      !$("search").value
    ) {
      title = "No items found by these three checks";
      copy = r.mapping_issues.length
        ? "Some file labels were not confirmed, so checks were skipped. This is not an all-clear."
        : "No unrecorded payment, repeated debit pattern or higher rate margin was found. Other differences can still exist; compare the payment amounts above.";
    }
    $("exception-list").innerHTML =
      `<div class="empty-state"><div class="${busy ? "busy-dot" : "empty-icon"}">${busy ? "" : "✓"}</div><h3>${escape(title)}</h3><p>${escape(copy)}</p></div>`;
  }
}
function showEvidence(exId) {
  const item = current.engine_exceptions.find((entry) => entry.ex_id === exId);
  if (!item) return;
  const info = describe(item),
    account = accountFor(item.loan_id),
    explanation = explanationFor(exId);
  $("evidence-title").textContent = labels[item.ex_type];
  const factPairs = !account
    ? []
    : item.ex_type === "RATE_MARGIN_BREACH"
      ? [
          ["Agreed margin", account.contractual_margin + "%"],
          ["Recorded margin", account.charged_margin + "%"],
        ]
      : [
          ["Payment due", money(account.scheduled)],
          ["Net payment recorded", money(account.received)],
          ["Payment entries", account.posting_count],
        ];
  const extra =
    explanation?.verdict === "PASS"
      ? `<p>${escape(explanation.rationale)}</p><p class="form-help">This extra explanation passed the configured checks. It still needs your judgment.</p>`
      : `<p class="held-note">${explanation ? "An extra AI explanation is not available because it did not pass all checks. The payment figures and original records above remain available." : "An extra explanation is still being prepared. You can already inspect the payment figures."}</p>`;
  $("evidence-content").innerHTML =
    `<p class="issue-kicker">${escape(item.loan_id)}${account ? " · " + month(account.period) : ""}</p><p class="detail-intro">${escape(info.body)}</p><div class="detail-facts">${factPairs.map(([label, value]) => `<div><span>${label}</span><strong>${escape(value)}</strong></div>`).join("")}</div><div class="detail-next"><h3>What to look at</h3><p>${escape(info.next)}</p></div><h3>Where these figures came from</h3>${account?.posting_count === 0 ? '<p class="form-help">No payment row exists for this account in the supplied payment file.</p>' : ""}${item.evidence
      .map((row) => {
        const filename = row.file.split("/").pop(),
          kind = fileKinds[filename];
        return `<section class="file-evidence"><h3>${escape(fileLabels[kind] || filename)}</h3><small>${escape(filename)} · row ${row.row_number}</small><dl class="source-fields">${Object.entries(
          row.raw,
        )
          .map(([raw, value]) => {
            const field = current.confirmed_mapping?.[kind]?.[raw];
            const formatted = [
              "scheduled_amount",
              "received_amount",
              "reported_amount",
            ].includes(field)
              ? money(value)
              : value;
            return `<div><dt>${escape(fields[field] || raw)}</dt><dd>${escape(formatted)}</dd></div>`;
          })
          .join("")}</dl></section>`;
      })
      .join(
        "",
      )}<details class="detail-disclosure"><summary>Extra explanation</summary>${extra}</details><details class="detail-disclosure"><summary>Original rows &amp; technical checks</summary><div class="engine-fact">${escape(item.detail)}</div>${
      explanation
        ? Object.entries(explanation.scores)
            .map(
              ([name, score]) =>
                `<div class="score-detail"><span>${escape(name.replaceAll("_", " "))}</span><span>${Math.round(score * 100)}%</span></div>`,
            )
            .join("") +
          Object.values(explanation.findings)
            .flat()
            .map((finding) => `<p class="finding">${escape(finding)}</p>`)
            .join("")
        : ""
    }${item.evidence.map((row) => `<h3>${escape(row.file.split("/").pop())} · line ${row.row_number}</h3><pre>${escape(row.raw_text)}</pre>`).join("")}</details>`;
  $("evidence-dialog").showModal();
}
function renderAnalytics() {
  if (!analytics || !current) return;
  const a = analytics,
    means = a.validator_means || {};
  $("trace-label").textContent =
    {
      local: "Local audit",
      live: "Direct HTTP + local audit",
      "sdk-local": "SDK → local capture",
      "sdk-live": "Disseqt SDK + local audit",
    }[current.trace_mode] || "Trace transport";
  $("validation-pulse").innerHTML = Object.keys(means).length
    ? Object.entries(validatorLabels)
        .map(
          ([key, label]) =>
            `<div class="pulse-row"><div><span>${label}</span><span>${Math.round((means[key] ?? 0) * 100)}%</span></div><div class="bar"><span class="${means[key] < 1 ? "warn" : ""}" style="width:${(means[key] ?? 0) * 100}%"></span></div></div>`,
        )
        .join("")
    : '<p class="muted">No explanation checks yet.</p>';
  $("ground-truth").innerHTML = current.score
    ? `<strong>${Math.round(current.score.recall * 100)}% recall</strong><span>${current.score.true_positives} found · ${current.score.false_positives} unexpected · ${current.score.false_negatives} missed</span>`
    : "<strong>Not scored here</strong><span>Uploaded files do not include a generated answer key.</span>";
  $("analytics-summary").innerHTML =
    `<div><strong>${(a.active_duration_ms / 1000).toFixed(1)}s</strong><span>Processing time · confirmation wait excluded</span></div><div><strong>${a.model_calls.length}</strong><span>Model operations</span></div><div><strong>${a.token_total === null ? "Unknown" : a.token_total.toLocaleString()}</strong><span>Recorded model tokens</span></div><div><strong>${a.estimated_api_cost_usd === null ? "Unknown" : "$" + a.estimated_api_cost_usd.toFixed(2) + " USD"}</strong><span>${escape(a.cost_note)}</span></div>`;
  const max = Math.max(1, ...a.span_timeline.map((span) => span.duration_ms));
  $("timeline").innerHTML = a.span_timeline
    .map(
      (span, index) =>
        `<div class="timeline-row"><span>${String(index + 1).padStart(2, "0")}</span><div>${escape(span.name)}${span.status === "error" ? '<span class="amber"> · failed</span>' : ""}</div><small>${escape(span.kind.replace("_EXEC", "").toLowerCase())}</small><div class="timeline-bar"><div style="width:${Math.max(1, (span.duration_ms / max) * 100)}%"></div></div><span>${span.duration_ms < 1000 ? span.duration_ms.toFixed(0) + " ms" : (span.duration_ms / 1000).toFixed(1) + " s"}</span></div>`,
    )
    .join("");
  $("baseline-drift").textContent = a.drift
    ? `Difference from “${a.baseline.label}”: ${(a.drift.active_duration_ms / 60000).toFixed(2)} minutes; ${a.drift.exception_count >= 0 ? "+" : ""}${a.drift.exception_count} items. Compare the same account set for a meaningful result.`
    : "No baseline recorded.";
  if (a.delivery_errors.length)
    notice(
      "Some audit deliveries failed. The local processing records have been retained.",
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
  link.download = "payment-check-" + current.run_id + ".json";
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
    let previous;
    try {
      previous = localStorage.getItem("uc1-selected-run");
    } catch (_) {
      /* Optional preference. */
    }
    if (runs.length)
      await selectRun(
        runs.some((run) => run.run_id === previous) ? previous : runs[0].run_id,
      );
    try {
      examples = await api("/examples");
      renderExamples();
    } catch (_) {
      $("example-cards").innerHTML =
        '<p class="chart-empty">The example library is unavailable. The monthly sample can still be opened from Check payment files.</p>';
    }
  } catch (error) {
    notice("Cannot reach the payment service: " + error.message);
  }
}
init();
