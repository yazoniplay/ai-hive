const DEFAULT_RELAY="https://ai-hive.onrender.com";
const AGENTS=["chatgpt","claude","gemini"];
let relay=DEFAULT_RELAY,lastTaskAt=0;
async function loadSettings(){const s=await chrome.storage.local.get(["relayUrl"]);relay=(s.relayUrl||DEFAULT_RELAY).replace(/\/$/,"")}
chrome.runtime.onInstalled.addListener(async()=>{await loadSettings();chrome.alarms.create("hive-poll",{periodInMinutes:0.5})});
chrome.runtime.onStartup.addListener(loadSettings);
chrome.storage.onChanged.addListener(c=>{if(c.relayUrl)relay=(c.relayUrl.newValue||DEFAULT_RELAY).replace(/\/$/,"")});
async function post(path,data){const r=await fetch(relay+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});if(!r.ok)throw Error("Relay HTTP "+r.status);return r.json()}
async function poll(){try{const tabs=await chrome.tabs.query({});for(const agent of AGENTS){const matches=tabs.filter(t=>t.url&&(agent==="chatgpt"?t.url.startsWith("https://chatgpt.com/"):agent==="claude"?t.url.startsWith("https://claude.ai/"):t.url.startsWith("https://gemini.google.com/")));if(!matches.length)continue;await post("/api/register",{agent});const r=await fetch(relay+"/api/next/"+agent+"?after="+lastTaskAt);if(!r.ok)continue;const data=await r.json();for(const task of data.tasks||[]){if(task.created_at<=lastTaskAt)continue;for(const tab of matches){try{await chrome.tabs.sendMessage(tab.id,{type:"HIVE_TASK",task})}catch(_){}}lastTaskAt=Math.max(lastTaskAt,task.created_at)}}}catch(e){console.warn("[AI Hive] Poll failed:",e.message)}}
chrome.alarms.onAlarm.addListener(a=>{if(a.name==="hive-poll")poll()});
chrome.runtime.onMessage.addListener((m,s,reply)=>{if(m.type==="HIVE_SEND_EVENT"){post("/api/message",m.payload).then(reply).catch(e=>reply({error:e.message}));return true}if(m.type==="HIVE_GET_RELAY")reply({relay})});
