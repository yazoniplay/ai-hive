(() => {
  if (window.__AI_HIVE_CONNECTOR__) return;
  window.__AI_HIVE_CONNECTOR__ = true;
  const host = location.hostname;
  const agent = host === "chatgpt.com" ? "chatgpt" : host === "claude.ai" ? "claude" : "gemini";
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  let working = false;
  let activeJob = null;
  let lastAnswer = "";

  function inputElement() {
    if (agent === "chatgpt") return document.querySelector("#prompt-textarea") || document.querySelector('[contenteditable="true"][data-placeholder]');
    if (agent === "claude") return document.querySelector('[contenteditable="true"].ProseMirror') || document.querySelector('[contenteditable="true"]');
    return document.querySelector("rich-textarea [contenteditable=true]") || document.querySelector('[contenteditable="true"]') || document.querySelector("textarea");
  }
  function sendButton() {
    const selectors = agent === "chatgpt" ? ['button[data-testid="send-button"]'] :
      ['button[aria-label*="Send"]', 'button[aria-label*="send"]'];
    for (const selector of selectors) {
      const button = document.querySelector(selector);
      if (button && !button.disabled) return button;
    }
    return null;
  }
  function assistantAnswer() {
    let selectors = agent === "chatgpt" ? ['[data-message-author-role="assistant"]'] :
      agent === "claude" ? ['[data-testid="chat-message"]', '[data-message-author-role="assistant"]'] :
      ['message-content', '[data-message-author-role="assistant"]'];
    let nodes = [];
    for (const selector of selectors) {
      nodes = [...document.querySelectorAll(selector)].filter(node => (node.innerText || "").trim());
      if (nodes.length) break;
    }
    if (!nodes.length) nodes = [...document.querySelectorAll("main article, main [role=article]")].filter(node => (node.innerText || "").trim());
    return nodes.length ? (nodes[nodes.length - 1].innerText || "").trim() : "";
  }
  function sendRuntime(message) {
    return new Promise(resolve => chrome.runtime.sendMessage(message, response => {
      const error = chrome.runtime.lastError;
      resolve(error ? {error: error.message} : (response || {}));
    }));
  }
  async function sendResult(job, text, error = false) {
    await sendRuntime({type: "HIVE_JOB_RESULT", payload: {job_id: job.id, agent, text, error}});
  }
  async function runJob(job) {
    if (working || !job || !job.prompt) return;
    working = true;
    activeJob = job;
    try {
      const input = inputElement();
      if (!input) {
        await sendResult(job, "Connector could not find the chat input. The website UI may have changed.", true);
        return;
      }
      const before = assistantAnswer();
      input.focus();
      if (input.tagName === "TEXTAREA" || input.tagName === "INPUT") {
        const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
        if (setter) setter.call(input, job.prompt); else input.value = job.prompt;
        input.dispatchEvent(new Event("input", {bubbles: true}));
      } else {
        input.textContent = job.prompt;
        input.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: job.prompt}));
      }
      await sleep(500);
      const button = sendButton();
      if (button) button.click();
      else input.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", code: "Enter", bubbles: true}));
      await sendRuntime({type: "HIVE_EVENT", payload: {agent, task_id: job.task_id, kind: "connector", text: "Submitted round " + job.round + " prompt to " + agent + "."}});
      const deadline = Date.now() + 210000;
      let previous = "", stable = 0, changed = false;
      while (Date.now() < deadline) {
        await sleep(2500);
        const current = assistantAnswer();
        if (current && current !== before) changed = true;
        if (changed && current && current === previous) stable++; else stable = 0;
        previous = current;
        if (changed && stable >= 3 && current.length > 0) {
          if (current !== lastAnswer) {
            lastAnswer = current;
            await sendResult(job, current.slice(0, 28000), false);
          }
          return;
        }
      }
      await sendResult(job, "Timed out waiting for a completed response. Check that the AI tab is open and responsive, then retry the task.", true);
    } catch (error) {
      await sendResult(job, "Connector error: " + (error?.message || String(error)), true);
    } finally {
      working = false;
      activeJob = null;
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "HIVE_RUN_JOB") {
      if (working) { sendResponse({ok: false, busy: true}); return; }
      runJob(message.job);
      sendResponse({ok: true, accepted: true});
    }
  });
  sendRuntime({type: "HIVE_EVENT", payload: {agent, kind: "status", text: "AI Hive connector loaded on " + location.hostname}});
})();