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
  let step = 0,
    run = current,
    highlightTimer;
  const lessons = [
    {
      label: "Start here",
      title: "Three questions. One payment picture.",
      description:
        "This page helps you understand a month of mortgage payment records. Try the sample accounts first, then choose one account to see its own figures.",
      visual: `<div class="lesson-flow"><div><span>WHAT WAS DUE?</span><b>Your scheduled payment</b><p>The amount expected for the month.</p></div><div><span>WHAT WAS RECORDED?</span><b>Your payment entries</b><p>The money shown in the payment file.</p></div><div><span>WHAT NEEDS A LOOK?</span><b>Differences in the records</b><p>Items to compare with the original files.</p></div></div>`,
      instruction:
        "Choose an account in the Showing dropdown. All accounts shown here are invented examples, not your personal mortgage account.",
      action: "desk",
    },
    {
      label: "Try example files",
      title: "Start with a small example.",
      description:
        "Example files lets you try a missing payment, a possible repeated collection or a higher rate margin. You can use a pack directly, or download its CSVs and upload them yourself.",
      visual: `<div class="lesson-files"><div><b>Payment schedule</b><span>What was due and which margin was agreed.</span></div><div><b>Payment record</b><span>The individual payment entries.</span></div><div><b>Lender report</b><span>The cash and rate margin reported by the lender.</span></div></div>`,
      instruction:
        "Choose Use these files on an example card. Tick the sample-data box, then Read these files. Quick practice uses fixed explanations; local AI may take a few minutes.",
      action: "examples",
    },
    {
      label: "Check file labels",
      title: "Make sure we read the right figures.",
      description:
        "Different files use different column names. Before we compare payments, we ask you to confirm what each column means. Read the example values beside each dropdown.",
      visual: `<div class="lesson-mapping"><span class="lesson-caption">EXAMPLE · a label in a payment schedule</span><div><code>ScheduledInstalment</code><span aria-hidden="true">→</span><b>Payment due</b></div><p>An amount due belongs here. An account number or percentage does not.</p></div><dl class="lesson-terms"><div><dt>Payment due / Payment recorded</dt><dd>What was expected / what appears in the payment file.</dd></div><div><dt>Agreed / Recorded rate margin</dt><dd>The percentage in the agreement / the percentage in the lender report.</dd></div></dl>`,
      instruction:
        "Check all three files and correct any dropdown that is wrong. Then tick the review box and choose Confirm & check payments. Help never confirms this for you.",
      action: "mapping",
    },
    {
      label: "Read the charts",
      title: "Follow the money, account by account.",
      description:
        "The bars compare the amount due with the amount recorded. The circle counts accounts with matching, lower or higher payment amounts. Choose one account to narrow the view.",
      visual: `<div class="lesson-queues"><div><span class="badge amber-bg">Less received</span><h3>A shortfall in the file</h3><p>We add shortfalls separately for each account.</p></div><div><span class="badge neutral">More received</span><h3>An extra amount in the file</h3><p>Extra money on another account cannot cancel a shortfall.</p></div></div><p class="lesson-caption">A matching payment does not prove the rate is correct. No mortgage balance or repayment trend is inferred from these files.</p>`,
      instruction:
        "Open See individual accounts and amounts for a closer look. Then read Things to take a closer look at. Each item gives you the relevant figures.",
      action: "results",
    },
    {
      label: "Understand an item",
      title: "See why an item needs attention.",
      description:
        "Select See details beside an item. The page explains what the files show, highlights the amounts or margins, and points to the original payment records.",
      visual: `<ol class="lesson-checklist"><li><b>Read the simple description.</b><span>For example: a payment was due, but none is recorded for the month.</span></li><li><b>Compare the source figures.</b><span>The file names and row numbers let you find the original records.</span></li><li><b>Use extra explanations if helpful.</b><span>AI text is optional and is withheld when it does not pass the checks. The source figures remain available.</span></li></ol>`,
      instruction:
        "A repeated-payment pattern is a reason to inspect the entries. It does not prove a collection was unauthorised. A rate margin is only one part of a rate, not the full interest rate or APR.",
      action: "evidence",
    },
    {
      label: "Explore another example",
      title: "Try a different set of payment records.",
      description:
        "The example library includes matching payments, shortfalls, repeated debits and differences in margins. Each pack has notes explaining what to expect.",
      visual: `<dl class="lesson-terms final-terms"><div><dt>Download a CSV pack</dt><dd>Unzip it and upload its three CSVs together to try the full file-reading flow.</dd></div><div><dt>Download results</dt><dd>Saves the current check as a JSON file, including source evidence.</dd></div><div><dt>Check details</dt><dd>Optional processing and explanation checks. Start with the payment overview for the financial figures.</dd></div></dl>`,
      instruction:
        "Use Help & tour whenever you need a reminder. This demo shows one month at a time; restarting its server clears the on-screen check history.",
      action: "examples",
    },
  ];

  function remember() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ dismissed: true }));
    } catch (_) {
      /* Tutorial state is optional. */
    }
    $("tutorial-welcome").hidden = true;
  }

  function actionLabel(action) {
    if (action === "new") return "Choose payment files →";
    if (action === "examples") return "Show example files →";
    if (action === "mapping")
      return run?.status === "awaiting_confirmation"
        ? "Show my file labels →"
        : "Choose files to try this →";
    if (action === "activity") return "Show check details →";
    if (action === "results" || action === "evidence")
      return "Show the payment results →";
    return "Show the payment overview →";
  }

  function renderLesson() {
    const lesson = lessons[step];
    $("tutorial-progress").textContent =
      `STEP ${step + 1} OF ${lessons.length}`;
    $("tutorial-title").textContent = lesson.title;
    $("tutorial-description").textContent = lesson.description;
    // Lesson HTML is static, authored help content; it never includes run data.
    $("tutorial-visual").innerHTML = lesson.visual;
    $("tutorial-instruction").textContent = lesson.instruction;
    $("tutorial-show").textContent = actionLabel(lesson.action);
    $("tutorial-back").disabled = step === 0;
    $("tutorial-next").textContent =
      step === lessons.length - 1 ? "Finish tour ✓" : "Next →";
    $("tutorial-chapters")
      .querySelectorAll("button")
      .forEach((button, index) => {
        if (index === step) button.setAttribute("aria-current", "step");
        else button.removeAttribute("aria-current");
      });
    $("tutorial-title").focus({ preventScroll: true });
    $("tutorial-title").scrollIntoView({ block: "nearest" });
  }

  function openTutorial(index = 0) {
    step =
      Number.isInteger(index) && index >= 0 && index < lessons.length
        ? index
        : 0;
    if (!dialog.open) dialog.showModal();
    renderLesson();
  }

  function pointTo(selector, view = "desk") {
    switchView(view);
    document
      .querySelectorAll(".guide-highlight")
      .forEach((item) => item.classList.remove("guide-highlight"));
    clearTimeout(highlightTimer);
    const target = document.querySelector(selector);
    if (!target || target.hidden) return;
    if (!target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
      target.addEventListener(
        "blur",
        () => target.removeAttribute("tabindex"),
        { once: true },
      );
    }
    target.focus({ preventScroll: true });
    target.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "center",
    });
    target.classList.add("guide-highlight");
    highlightTimer = setTimeout(
      () => target.classList.remove("guide-highlight"),
      4500,
    );
  }

  function showAction(action) {
    if (
      action === "new" ||
      (action === "mapping" && run?.status !== "awaiting_confirmation")
    )
      openRun();
    else if (action === "mapping") pointTo("#mapping-panel");
    else if (action === "results" || action === "evidence")
      pointTo(".outcomes-panel");
    else if (action === "activity") pointTo("#audit-view", "audit");
    else if (action === "examples") pointTo("#example-cards", "examples");
    else pointTo(".next-step");
  }

  $("tutorial-chapters").innerHTML = lessons
    .map(
      (lesson, index) =>
        `<button data-lesson="${index}"><span>${String(index + 1).padStart(2, "0")}</span>${lesson.label}</button>`,
    )
    .join("");
  $("tutorial-chapters")
    .querySelectorAll("button")
    .forEach((button) => {
      button.addEventListener("click", () => {
        step = Number(button.dataset.lesson);
        renderLesson();
      });
    });
  $("help-tour").addEventListener("click", () => openTutorial());
  $("start-tour").addEventListener("click", () => openTutorial());
  document.querySelectorAll("[data-tutorial]").forEach((button) => {
    button.addEventListener("click", () =>
      openTutorial(Number(button.dataset.tutorial)),
    );
  });
  $("dismiss-welcome").addEventListener("click", remember);
  $("close-tour").addEventListener("click", () => dialog.close());
  $("skip-tour").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    remember();
    // The introduction disappears after closing. Restore focus to a visible
    // entry point if the browser restored it to that now-hidden introduction.
    if (
      $("tutorial-welcome").contains(document.activeElement) ||
      document.activeElement === document.body
    )
      $("help-tour").focus();
  });
  $("tutorial-back").addEventListener("click", () => {
    step = Math.max(0, step - 1);
    renderLesson();
  });
  $("tutorial-next").addEventListener("click", () => {
    if (step === lessons.length - 1) dialog.close();
    else {
      step += 1;
      renderLesson();
    }
  });
  $("tutorial-show").addEventListener("click", () => {
    dialog.close();
    showAction(lessons[step].action);
  });

  function updateGuide(nextRun) {
    run = nextRun;
    let title = "Try a sample payment check",
      copy =
        "Choose a small example to see how payments are compared. The three sample files are already prepared.",
      button = "Explore examples →",
      action = () => showAction("examples");
    if (run?.status === "awaiting_confirmation") {
      title = "Are we reading the right figures?";
      copy =
        "Check each file label and its example values below. Confirm the meanings before payment comparisons begin.";
      button = "Help with file labels →";
      action = () => openTutorial(2);
    } else if (run?.status === "complete") {
      const found = run.engine_exceptions.length;
      title = found
        ? "Your payment picture is ready"
        : "No items found by the three checks";
      copy = run.mapping_issues.length
        ? "Some file labels were not confirmed. Parts of the check could not run, so review the message above."
        : "Start with the amounts due and recorded. Choose one sample account to see its figures, then open any item below for a simple explanation.";
      button = "Help with the results →";
      action = () => openTutorial(3);
    } else if (run?.status === "input_blocked" || run?.status === "error") {
      title = "The files need a closer look";
      copy =
        "Read the message above. Check the file labels and sample values before starting a new check.";
      button = "Show check details →";
      action = () => showAction("activity");
    } else if (run && activeStatuses.has(run.status)) {
      const preparing = ["created", "ingesting", "proposing_mapping"].includes(
        run.status,
      );
      title = preparing
        ? "We’re reading your file labels"
        : "We’re comparing payments and preparing explanations";
      copy = preparing
        ? "You’ll confirm the meanings before payment comparisons start. Local AI can take a few minutes."
        : "The page updates automatically. Payment figures appear as soon as they are ready; extra explanations may take longer.";
      button = "How does this work?";
      action = () => openTutorial(0);
    }
    $("next-step-title").textContent = title;
    $("next-step-copy").textContent = copy;
    $("next-step-action").textContent = button;
    $("next-step-action").onclick = action;
    if (dialog.open)
      $("tutorial-show").textContent = actionLabel(lessons[step].action);
  }

  $("tutorial-welcome").hidden = Boolean(saved.dismissed);
  document.addEventListener("uc1:run-rendered", (event) =>
    updateGuide(event.detail),
  );
  updateGuide(current);
})();
