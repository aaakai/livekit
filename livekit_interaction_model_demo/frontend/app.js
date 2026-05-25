const timeline = document.querySelector("#timeline");
const health = document.querySelector("#health");
const eventCount = document.querySelector("#event-count");
const floorState = document.querySelector("#floor-state");
const actionState = document.querySelector("#action-state");
const latestTranscript = document.querySelector("#latest-transcript");
const soundPlan = document.querySelector("#sound-plan");
const buttons = [...document.querySelectorAll(".scenario-button")];

let lastSeq = 0;
let polling = null;

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

function eventClass(event) {
  if (event.event_type === "interrupt") return "interrupt";
  if (event.event_type === "barge_in") return "barge";
  if (event.actor === "user") return "user";
  if (event.actor === "assistant") return "assistant";
  if (event.actor === "floor") return "floor";
  return "";
}

function eventSummary(event) {
  const payload = event.payload || {};
  if (payload.text) return payload.text;
  if (payload.action && typeof payload.action === "object") {
    const action = payload.action;
    return `${action.action || action.type}${action.reason ? ` · ${action.reason}` : ""}`;
  }
  if (payload.action) return `${payload.action}${payload.reason ? ` · ${payload.reason}` : ""}`;
  if (payload.state) return `${payload.state}${payload.reason ? ` · ${payload.reason}` : ""}`;
  if (payload.task) return payload.task;
  if (payload.scenario) return `Scenario ${payload.scenario}`;
  if (payload.status) return `${payload.status}${payload.duration_s ? ` · ${payload.duration_s}s` : ""}`;
  if (payload.plan_id) return `${payload.action} · azimuth ${payload.spatial?.azimuth_deg ?? 0}deg`;
  return JSON.stringify(payload);
}

function updateInspector(events) {
  const floor = [...events].reverse().find((event) => event.event_type === "floor_decision");
  const action = [...events].reverse().find((event) => event.event_type === "judge_action");
  const transcript = [...events]
    .reverse()
    .find((event) => event.event_type === "partial_transcript" || event.event_type === "final_transcript");
  const plan = [...events].reverse().find((event) => event.event_type === "sound_plan");

  floorState.value = floor?.payload?.state || "IDLE";
  actionState.value = action?.payload?.action?.action || "LISTEN";
  latestTranscript.textContent = transcript?.payload?.text || "等待场景运行。";
  soundPlan.textContent = plan ? JSON.stringify(plan.payload, null, 2) : "{}";
}

function render(events) {
  eventCount.textContent = `${events.length} events`;
  updateInspector(events);

  const fragment = document.createDocumentFragment();
  for (const event of events) {
    const item = document.createElement("li");
    item.className = "event-row";

    const ts = new Date(event.ts * 1000);
    const time = document.createElement("time");
    time.textContent = `${String(ts.getHours()).padStart(2, "0")}:${String(ts.getMinutes()).padStart(2, "0")}:${String(ts.getSeconds()).padStart(2, "0")}.${String(ts.getMilliseconds()).padStart(3, "0")}`;

    const body = document.createElement("div");
    body.className = "event-body";
    const type = document.createElement("span");
    type.className = `event-type ${eventClass(event)}`;
    type.textContent = `${event.seq}. ${event.event_type}`;
    const text = document.createElement("p");
    text.className = "event-text";
    text.textContent = eventSummary(event);
    body.append(type, text);
    item.append(time, body);
    fragment.append(item);
  }

  timeline.replaceChildren(fragment);
  if (events.at(-1)?.seq !== lastSeq) {
    lastSeq = events.at(-1)?.seq || 0;
    timeline.scrollTop = timeline.scrollHeight;
  }
}

async function poll() {
  try {
    const data = await api("/api/events");
    render(data.events || []);
    health.textContent = "online";
    health.classList.add("online");
  } catch (error) {
    health.textContent = "offline";
    health.classList.remove("online");
  }
}

async function startScenario(scenario) {
  buttons.forEach((button) => {
    button.disabled = true;
    button.classList.toggle("active", button.dataset.scenario === scenario);
  });
  try {
    await api(`/api/scenario/${scenario}`, { method: "POST" });
    await poll();
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
      button.classList.remove("active");
    });
  }
}

buttons.forEach((button) => {
  button.addEventListener("click", () => {
    startScenario(button.dataset.scenario);
  });
});

polling = window.setInterval(poll, 800);
poll();

window.addEventListener("beforeunload", () => {
  if (polling) window.clearInterval(polling);
});
