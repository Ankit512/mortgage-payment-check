"use strict";

// The guide only changes presentation. Run creation and confirmation use the
// existing forms, including their synthetic-data and mapping-review checkboxes.
(() => {
  const storageKey = "uc1-tutorial-v1";
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(storageKey) || "{}") || {};
  } catch (_) {
    // Help remains available when browser storage is restricted or cleared.
  }
  const dialog = $("tutorial-dialog");
  let step = 0, run = current, highlightTimer;
  const lessons = [
    {
      label: "The big picture",
      title: "Check what was due against what happened.",
      description: "Reconciliation means comparing records for the same loan and month. This workspace looks for missing payments, duplicate debit patterns, and margins charged above the contract.",
      visual: `<div class="lesson-flow"><div><span>01 · PROPOSE</span><b>AI suggests the columns</b><p>It helps translate the file headings.</p></div><div><span>02 · REVIEW</span><b>You check the mapping</b><p>You decide when the checks can start.</p></div><div><span>03 · CHECK</span><b>The engine calculates</b><p>AI then explains the findings.</p></div></div>`,
      instruction: "Start with the sample files. When a result appears, use its source rows to check the evidence. No payment is moved by this workspace.",
      action: "desk",
    },
    {
      label: "Start a run",
      title: "Your first run needs no uploads.",
      description: "A run is one check of a loan book. New reconciliation includes three synthetic files for one month. Keep seed 42 and 40 loans to explore the supplied example.",
      visual: `<div class="lesson-files"><div><b>Servicing extract</b><span>What was due: scheduled payments and contractual margins.</span></div><div><b>Payments file</b><span>What was posted: individual payment entries.</span></div><div><b>Investor report</b><span>What was reported: cash collected and the margin charged.</span></div></div><p class="lesson-caption">Seed selects the sample dataset; the loan count sets its size. Matching both recreates the same files.</p>`,
      instruction: "Choose Qwen for local AI, or Mock for a quick practice run with fixed explanations. Confirm the data is synthetic, then select Prepare mapping. Qwen may take a few minutes.",
      action: "new",
    },
    {
      label: "Check the mapping",
      title: "Tell the engine what each column means.",
      description: "Mapping connects a source heading to the field our checks use. The model proposes a match; you verify it using the sample values. The run pauses here until you confirm.",
      visual: `<div class="lesson-mapping"><span class="lesson-caption">ILLUSTRATIVE MAPPING · servicing extract</span><div><code>ScheduledInstalment</code><span aria-hidden="true">→</span><code>scheduled_amount</code></div><p>A payment amount belongs here. A loan ID or percentage does not.</p></div><dl class="lesson-terms"><div><dt>loan_id / period</dt><dd>The same account and reporting month across the files.</dd></div><div><dt>scheduled / received / reported amount</dt><dd>Due / posted / reported cash. These are different fields.</dd></div><div><dt>contractual / charged margin</dt><dd>Agreed / applied percentage. Check the units as well as the name.</dd></div></dl>`,
      instruction: "Check all three files, correct dropdowns as needed, then tick “I reviewed the mappings” and choose Confirm & reconcile. Unmapped fields can leave some checks unable to run.",
      action: "mapping",
    },
    {
      label: "Read the results",
      title: "An exception is something to investigate.",
      description: "The engine compares each loan’s records using fixed rules. “Exceptions found” counts those findings. Each finding gets an AI explanation that is checked before it can appear in the remediation log.",
      visual: `<div class="lesson-queues"><div><span class="badge green-bg">Passed validation</span><h3>Explanation available</h3><p>The draft passed the configured checks. It still needs your judgment.</p></div><div><span class="badge amber-bg">Held for review</span><h3>Explanation withheld</h3><p>A check or model call failed. The engine finding and source evidence remain available.</p></div></div><p class="lesson-caption">“Passed” does not mean the loan is problem-free or a payment is approved. The checks can miss errors in meaning.</p>`,
      instruction: "Open both queues. A held explanation does not erase an exception. If the run shows a coverage warning, resolve it before treating missing findings as an all-clear.",
      action: "results",
    },
    {
      label: "Inspect the evidence",
      title: "Follow a finding back to the records.",
      description: "Select the source rows button on any exception. It opens the calculated finding, any available explanation, the check results, and the original CSV records with file names and line numbers.",
      visual: `<ol class="lesson-checklist"><li><b>Read the calculated finding.</b><span>Which loan, which month, and which amounts or margins triggered the rule?</span></li><li><b>Compare the original rows.</b><span>Check the source values against the finding. An absent payment has no payment row to show.</span></li><li><b>Read the explanation or hold reason.</b><span>A held draft stays hidden. Failed checks explain why it needs attention.</span></li></ol>`,
      instruction: "Pick one missing payment and trace its scheduled amount to the servicing record. For a duplicate debit pattern, check the postings; the pattern alone does not establish authorisation.",
      action: "evidence",
    },
    {
      label: "Explore & repeat",
      title: "You’re ready to explore a run.",
      description: "Run activity shows the processing steps, time and model usage. Connections shows the configured integrations. Qwen works locally without an API key; local traces do not mean Disseqt’s cloud is connected.",
      visual: `<dl class="lesson-terms final-terms"><div><dt>Seeded-data check</dt><dd>Recall is the share of planted exceptions found in the generated sample. Uploaded files have no generated answer key.</dd></div><div><dt>Validation pulse</dt><dd>These percentages summarise the checks. They are not AI confidence scores.</dd></div><div><dt>Export JSON</dt><dd>Downloads the run’s findings and available explanations. Held drafts stay hidden.</dd></div></dl>`,
      instruction: "Explore the current run or start another from New reconciliation. Help & tour stays available whenever you need it. Run history is kept for this server session; restarting the server clears it.",
      action: "activity",
    },
  ];

  function remember() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ dismissed: true }));
    } catch (_) { /* Tutorial state is optional. */ }
    $("tutorial-welcome").hidden = true;
  }

  function actionLabel(action) {
    if (action === "new") return "Open new run →";
    if (action === "mapping") return run?.status === "awaiting_confirmation"
      ? "Show my mapping table →" : "Open a run to try mapping →";
    if (action === "activity") return "Show run activity →";
    if (action === "results" || action === "evidence") return "Show the exception workspace →";
    return "Show the reconciliation desk →";
  }

  function renderLesson() {
    const lesson = lessons[step];
    $("tutorial-progress").textContent = `STEP ${step + 1} OF ${lessons.length}`;
    $("tutorial-title").textContent = lesson.title;
    $("tutorial-description").textContent = lesson.description;
    // Lesson HTML is static, authored help content; it never includes run data.
    $("tutorial-visual").innerHTML = lesson.visual;
    $("tutorial-instruction").textContent = lesson.instruction;
    $("tutorial-show").textContent = actionLabel(lesson.action);
    $("tutorial-back").disabled = step === 0;
    $("tutorial-next").textContent = step === lessons.length - 1 ? "Finish tour ✓" : "Next →";
    $("tutorial-chapters").querySelectorAll("button").forEach((button, index) => {
      if (index === step) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    $("tutorial-title").focus({ preventScroll: true });
    $("tutorial-title").scrollIntoView({ block: "nearest" });
  }

  function openTutorial(index = 0) {
    step = Number.isInteger(index) && index >= 0 && index < lessons.length ? index : 0;
    if (!dialog.open) dialog.showModal();
    renderLesson();
  }

  function pointTo(selector, view = "desk") {
    switchView(view);
    document.querySelectorAll(".guide-highlight").forEach((item) => item.classList.remove("guide-highlight"));
    clearTimeout(highlightTimer);
    const target = document.querySelector(selector);
    if (!target || target.hidden) return;
    if (!target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
      target.addEventListener("blur", () => target.removeAttribute("tabindex"), { once: true });
    }
    target.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" });
    target.classList.add("guide-highlight");
    highlightTimer = setTimeout(() => target.classList.remove("guide-highlight"), 4500);
  }

  function showAction(action) {
    if (action === "new" || (action === "mapping" && run?.status !== "awaiting_confirmation")) openRun();
    else if (action === "mapping") pointTo("#mapping-panel");
    else if (action === "results" || action === "evidence") pointTo(".outcomes-panel");
    else if (action === "activity") pointTo("#audit-view", "audit");
    else pointTo(".next-step");
  }

  $("tutorial-chapters").innerHTML = lessons.map((lesson, index) =>
    `<button data-lesson="${index}"><span>${String(index + 1).padStart(2, "0")}</span>${lesson.label}</button>`,
  ).join("");
  $("tutorial-chapters").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => { step = Number(button.dataset.lesson); renderLesson(); });
  });
  $("help-tour").addEventListener("click", () => openTutorial());
  $("start-tour").addEventListener("click", () => openTutorial());
  document.querySelectorAll("[data-tutorial]").forEach((button) => {
    button.addEventListener("click", () => openTutorial(Number(button.dataset.tutorial)));
  });
  $("dismiss-welcome").addEventListener("click", remember);
  $("close-tour").addEventListener("click", () => dialog.close());
  $("skip-tour").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    remember();
    // The introduction disappears after closing. Restore focus to a visible
    // entry point if the browser restored it to that now-hidden introduction.
    if ($("tutorial-welcome").contains(document.activeElement) || document.activeElement === document.body)
      $("help-tour").focus();
  });
  $("tutorial-back").addEventListener("click", () => { step = Math.max(0, step - 1); renderLesson(); });
  $("tutorial-next").addEventListener("click", () => {
    if (step === lessons.length - 1) dialog.close();
    else { step += 1; renderLesson(); }
  });
  $("tutorial-show").addEventListener("click", () => {
    dialog.close();
    showAction(lessons[step].action);
  });

  function updateGuide(nextRun) {
    run = nextRun;
    let title = "Start with the included sample",
      copy = "Choose New reconciliation. The sample files are already included, so you don’t need to upload anything.",
      button = "Open new run →", action = () => openRun();
    if (run?.status === "awaiting_confirmation") {
      title = "Review the mapping before the checks start";
      copy = "Read each source heading and its sample values, then check the dropdown matches their meaning. After reviewing all three files, tick the review box and confirm.";
      button = "Show me how →"; action = () => openTutorial(2);
    } else if (run?.status === "complete") {
      const found = run.engine_exceptions.length, held = run.held_for_review.length;
      title = found ? "Open a finding and follow its source rows" : "Read the coverage notes before drawing a conclusion";
      copy = `${found} ${found === 1 ? "finding is" : "findings are"} ready to inspect. ${held ? `${held} ${held === 1 ? "explanation was" : "explanations were"} held; the underlying findings remain available.` : "Passed explanations still need your judgment."} ${run.mapping_issues.length ? "Some fields were not mapped, so detection coverage is reduced." : "The checks cover three exception patterns for one month."}`;
      button = "Help me read the results →"; action = () => openTutorial(3);
    } else if (run?.status === "input_blocked" || run?.status === "error") {
      title = "Check the run message before trying again";
      copy = "The run needs attention. Read the message above and check your synthetic source files and selected model. Starting another run will not repair the current one.";
      button = "Show run activity →"; action = () => showAction("activity");
    } else if (run && activeStatuses.has(run.status)) {
      const preparing = ["created", "ingesting", "proposing_mapping"].includes(run.status);
      title = preparing ? "Wait for the column mapping to appear" : "The checks are running. Results will appear below.";
      copy = preparing
        ? "The files are being scanned and their headings matched. Qwen may take a few minutes. You will be asked to review the mapping before reconciliation starts."
        : "The engine checks the numbers, then each explanation is drafted and validated. Qwen may take a few minutes. This page updates automatically.";
      button = "Show run activity →"; action = () => showAction("activity");
    }
    $("next-step-title").textContent = title;
    $("next-step-copy").textContent = copy;
    $("next-step-action").textContent = button;
    $("next-step-action").onclick = action;
    if (dialog.open) $("tutorial-show").textContent = actionLabel(lessons[step].action);
  }
  $("tutorial-welcome").hidden = Boolean(saved.dismissed);
  document.addEventListener("uc1:run-rendered", (event) => updateGuide(event.detail));
  updateGuide(current);
})();
