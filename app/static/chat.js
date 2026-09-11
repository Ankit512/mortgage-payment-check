"use strict";
(() => {
  let contextKey = "",
    previousTopic = null,
    pending = false,
    controller = null;
  const dialog = $("chat-dialog");
  const scopeKey = () =>
    `${current?.run_id || ""}:${selectedAccount}:${displayCurrency}`;
  const ready = () =>
    current?.payment_summary?.available &&
    ["explaining", "complete"].includes(current.status);
  function setControls() {
    $("chat-question").disabled = $("chat-send").disabled = pending || !ready();
    $("chat-suggestions")
      .querySelectorAll("button")
      .forEach((b) => (b.disabled = pending || !ready()));
  }
  function syncContext() {
    const key = scopeKey();
    if (key !== contextKey) {
      controller?.abort();
      controller = null;
      pending = false;
      previousTopic = null;
      contextKey = key;
      $("chat-messages").replaceChildren();
      $("chat-status").textContent = "";
      $("chat-question").value = "";
    }
    $("chat-context").textContent = ready()
      ? `${selectedAccount || "All accounts in this check"} · ${month(current.payment_summary.period)} · ${displayCurrency} · ${current.provider === "mock" ? "Quick practice guide" : "Qwen assistant"}`
      : "Start a payment check and confirm the file labels first. I can help once the payment figures are ready.";
    setControls();
  }
  function message(role, text) {
    const node = document.createElement("article");
    node.className = "chat-message " + role;
    if (text) node.textContent = text;
    $("chat-messages").append(node);
    return node;
  }
  function paragraph(parent, tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.append(node);
    return node;
  }
  $("open-chat").addEventListener("click", () => {
    syncContext();
    dialog.showModal();
    (ready() ? $("chat-question") : $("close-chat")).focus();
  });
  $("close-chat").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => $("open-chat").focus());
  document.addEventListener("uc1:scope-changed", syncContext);
  document.addEventListener("uc1:run-rendered", syncContext);
  $("chat-suggestions")
    .querySelectorAll("button")
    .forEach((button) => {
      button.addEventListener("click", () => {
        $("chat-question").value = button.textContent;
        $("chat-form").requestSubmit();
      });
    });
  $("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = $("chat-question").value.trim();
    if (!question || pending || !ready()) return;
    const key = contextKey,
      runId = current.run_id;
    controller = new AbortController();
    const requestController = controller;
    pending = true;
    setControls();
    message("user", question);
    $("chat-question").value = "";
    $("chat-status").textContent = "Looking at your payment check…";
    try {
      const reply = await api(`/runs/${runId}/chat`, {
        method: "POST",
        signal: requestController.signal,
        body: JSON.stringify({
          question,
          account_id: selectedAccount || null,
          currency: displayCurrency,
          previous_topic: previousTopic,
        }),
      });
      if (scopeKey() !== key) return;
      previousTopic = reply.topic;
      const node = message("assistant");
      paragraph(
        node,
        "small",
        `${reply.mode === "qwen" ? "Qwen · answers from records" : "Quick practice · answers from records"} · ${reply.account_id || "All accounts"} · ${reply.currency}`,
      );
      reply.blocks.forEach((block) => {
        paragraph(node, "h3", block.heading);
        paragraph(node, "p", block.text);
      });
      if (reply.citations.length) {
        const sources = document.createElement("details");
        paragraph(sources, "summary", "Supporting CSV records");
        reply.citations.forEach((source) => {
          paragraph(
            sources,
            "p",
            `${source.file}: ${source.rows.length ? "line(s) " + source.rows.join(", ") : "no matching account rows"}`,
          );
        });
        node.append(sources);
      }
      paragraph(node, "small", reply.currency_note);
      $("chat-status").textContent = "";
    } catch (error) {
      if (error.name !== "AbortError" && scopeKey() === key)
        $("chat-status").textContent = error.message;
    } finally {
      if (controller === requestController) {
        pending = false;
        controller = null;
        setControls();
        $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
        if (dialog.open) $("chat-question").focus();
      }
    }
  });
  syncContext();
})();
