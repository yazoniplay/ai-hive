const DEFAULT_RELAY = "https://ai-hive.onrender.com";
const AGENTS = ["chatgpt", "claude", "gemini"];
let relay = DEFAULT_RELAY;
const busyTabs = new Set();
async function loadSettings() {
  const saved = await chrome.storage.local.get(["relayUrl"]);
  relay = (saved.relayUrl || DEFAULT_RELAY).replace(/\/$/, "");
}
chrome.runtime.onInstalled.addListener(async () => {
  await loadSettings();
  chrome.alarms.create("hive-poll", {periodInMinutes: 0.5});
  poll();
});
chrome.runtime.onStartup.addListener(loadSettings);
chrome.storage.onChanged.addListener(changes => {
  if (changes.relayUrl) relay = (changes.relayUrl.newValue || DEFAULT_RELAY).replace(/\/$/, "");
});
async function request(path, options = {}) {
  const response = await fetch(relay + path, options);
  if (!response.ok) throw new Error("Relay HTTP " + response.status);
  return response.json();
}
async function post(path, data) {
  return request(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
}
async function poll() {
  try {
    const tabs = await chrome.tabs.query({});
    for (const agent of AGENTS) {
      const match = tabs.find(tab => tab.url && (
        agent === "chatgpt" ? tab.url.startsWith("https://chatgpt.com/") :
        agent === "claude" ? tab.url.startsWith("https://claude.ai/") :
        tab.url.startsWith("https://gemini.google.com/")
      ));
      if (!match) continue;
      await post("/api/register", {agent});
      const data = await request("/api/jobs/" + agent);
      for (const job of data.jobs || []) {
        if (busyTabs.has(match.id)) break;
        busyTabs.add(match.id);
        try {
          const reply = await chrome.tabs.sendMessage(match.id, {type: "HIVE_RUN_JOB", job});
          if (!reply || !reply.accepted) {
            // Leave the job to be retried when its server-side claim expires.
            console.warn("[AI Hive] Connector did not accept job", job.id);
          }
        } catch (error) {
          console.warn("[AI Hive] Could not dispatch job:", error.message);
        } finally {
          setTimeout(() => busyTabs.delete(match.id), 220000);
        }
        break;
      }
    }
  } catch (error) {
    console.warn("[AI Hive] Poll failed:", error.message);
  }
}
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "hive-poll") poll(); });
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "HIVE_EVENT") {
    post("/api/message", message.payload).then(sendResponse).catch(error => sendResponse({error: error.message}));
    return true;
  }
  if (message.type === "HIVE_JOB_RESULT") {
    post("/api/jobs/" + message.payload.job_id + "/result", {
      agent: message.payload.agent, text: message.payload.text, error: !!message.payload.error
    }).then(sendResponse).catch(error => sendResponse({error: error.message}));
    return true;
  }
  if (message.type === "HIVE_GET_RELAY") { sendResponse({relay}); }
});
