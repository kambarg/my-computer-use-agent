"use strict";

const EVENT_TYPES = [
  "assistant_text",
  "assistant_thinking",
  "tool_use",
  "tool_result",
  "run_finished",
  "run_failed",
  "run_cancelled",
];

const TERMINAL = new Set(["run_finished", "run_failed", "run_cancelled"]);

const state = {
  sessions: [],
  currentId: null,
  source: null,
  sending: false,
};

const ui = {
  list: document.getElementById("session-list"),
  newSession: document.getElementById("new-session"),
  title: document.getElementById("current-title"),
  status: document.getElementById("current-status"),
  deleteSession: document.getElementById("delete-session"),
  log: document.getElementById("event-log"),
  banner: document.getElementById("banner"),
  promptForm: document.getElementById("prompt-form"),
  prompt: document.getElementById("prompt"),
  send: document.getElementById("send"),
  desktop: document.getElementById("desktop"),
  placeholder: document.getElementById("desktop-placeholder"),
};

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 204) {
    return { ok: true, status: 204, data: null, retryAfter: null };
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  return {
    ok: response.ok,
    status: response.status,
    data,
    retryAfter: response.headers.get("Retry-After"),
  };
}

function detailOf(data, fallback) {
  if (data && typeof data.detail === "string") {
    return data.detail;
  }
  return fallback;
}

function showBanner(message) {
  if (!message) {
    ui.banner.hidden = true;
    ui.banner.textContent = "";
    return;
  }
  ui.banner.hidden = false;
  ui.banner.textContent = message;
}

function titleFromPrompt(prompt) {
  const line = prompt.trim().split("\n", 1)[0];
  return line.slice(0, 80) || null;
}

function shortId(id) {
  return id.slice(0, 8);
}

function currentSession() {
  return state.sessions.find((session) => session.id === state.currentId) || null;
}

function setBusy(busy) {
  const session = currentSession();
  const running = Boolean(session && session.status === "running");
  ui.send.disabled = busy || running;
  ui.prompt.disabled = busy;
}

async function refreshSessions() {
  const result = await request("GET", "/sessions");
  if (!result.ok) {
    showBanner(detailOf(result.data, "Could not list sessions"));
    return;
  }
  state.sessions = result.data;
  renderSessionList();
  renderCurrent();
}

function renderSessionList() {
  ui.list.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No sessions yet. Create one, or send a prompt.";
    ui.list.append(empty);
    return;
  }
  for (const session of state.sessions) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pick";
    button.dataset.id = session.id;
    if (session.id === state.currentId) {
      button.setAttribute("aria-current", "true");
    }
    const name = document.createElement("strong");
    name.textContent = session.title || shortId(session.id);
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = session.status;
    button.append(name, meta);
    button.addEventListener("click", () => selectSession(session.id));
    item.append(button);
    ui.list.append(item);
  }
}

function renderCurrent() {
  const session = currentSession();
  if (!session) {
    ui.title.textContent = "No session selected";
    ui.status.textContent = "";
    ui.status.removeAttribute("data-status");
    ui.deleteSession.hidden = true;
    setBusy(state.sending);
    return;
  }
  ui.title.textContent = session.title || shortId(session.id);
  ui.status.textContent = session.status;
  ui.status.dataset.status = session.status;
  ui.deleteSession.hidden = false;
  setBusy(state.sending);
}

function stopEvents() {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
}

function followEvents(sessionId) {
  stopEvents();
  ui.log.replaceChildren();
  const source = new EventSource(`/sessions/${sessionId}/events`);
  state.source = source;
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      appendEvent(JSON.parse(event.data));
    });
  }
}

function appendEvent(event) {
  const payload = event.payload || {};
  const item = document.createElement("li");
  item.className = payload.type || "unknown";
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = payload.type || "event";
  item.append(kind);
  item.append(bodyFor(payload));
  if (payload.screenshot && payload.screenshot.kind === "ref" && payload.screenshot.url) {
    const image = document.createElement("img");
    image.src = payload.screenshot.url;
    image.alt = "Desktop screenshot";
    item.append(image);
  }
  ui.log.append(item);
  item.scrollIntoView({ block: "end" });
  if (TERMINAL.has(payload.type)) {
    refreshSessions();
  }
}

function bodyFor(payload) {
  const block = document.createElement("div");
  if (payload.type === "assistant_text") {
    block.textContent = payload.text || "";
    return block;
  }
  if (payload.type === "assistant_thinking") {
    block.textContent = payload.thinking || "";
    return block;
  }
  if (payload.type === "tool_use") {
    block.textContent = payload.name || "tool";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(payload.input || {}, null, 2);
    block.append(pre);
    return block;
  }
  if (payload.type === "tool_result") {
    block.textContent = payload.error || payload.output || payload.system || "";
    return block;
  }
  if (payload.type === "run_failed") {
    block.textContent = payload.message || "run failed";
    return block;
  }
  if (payload.type === "run_finished") {
    block.textContent = "Run finished";
    return block;
  }
  if (payload.type === "run_cancelled") {
    block.textContent = "Run cancelled";
    return block;
  }
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(payload, null, 2);
  block.append(pre);
  return block;
}

function hideDesktop() {
  ui.desktop.hidden = true;
  ui.desktop.removeAttribute("src");
  ui.placeholder.hidden = false;
}

async function showDesktop(sessionId) {
  const response = await fetch(`/sessions/${sessionId}/desktop`, {
    redirect: "manual",
  });
  if (response.status === 409 || response.status === 404) {
    hideDesktop();
    return;
  }
  ui.placeholder.hidden = true;
  ui.desktop.hidden = false;
  ui.desktop.src = `/sessions/${sessionId}/desktop`;
}

async function selectSession(sessionId) {
  if (state.currentId === sessionId && state.source) {
    return;
  }
  state.currentId = sessionId;
  showBanner("");
  hideDesktop();
  renderSessionList();
  renderCurrent();
  followEvents(sessionId);
  await showDesktop(sessionId);
}

async function createSession(title) {
  const body = title ? { title } : undefined;
  const result = await request("POST", "/sessions", body);
  if (!result.ok) {
    showBanner(detailOf(result.data, "Could not create a session"));
    return null;
  }
  await refreshSessions();
  await selectSession(result.data.id);
  return result.data;
}

ui.newSession.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = ui.newSession.elements.title;
  const title = input.value.trim();
  input.value = "";
  await createSession(title);
});

ui.deleteSession.addEventListener("click", async () => {
  const sessionId = state.currentId;
  if (!sessionId) {
    return;
  }
  const result = await request("DELETE", `/sessions/${sessionId}`);
  if (!result.ok) {
    showBanner(detailOf(result.data, "Could not delete the session"));
    return;
  }
  stopEvents();
  state.currentId = null;
  ui.log.replaceChildren();
  hideDesktop();
  showBanner("");
  await refreshSessions();
});

ui.promptForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = ui.prompt.value.trim();
  if (!prompt || state.sending) {
    return;
  }
  showBanner("");
  state.sending = true;
  setBusy(true);
  try {
    let sessionId = state.currentId;
    if (!sessionId) {
      const session = await createSession(titleFromPrompt(prompt));
      if (!session) {
        return;
      }
      sessionId = session.id;
    }
    const result = await request("POST", `/sessions/${sessionId}/messages`, {
      prompt,
    });
    if (!result.ok) {
      let message = detailOf(result.data, "Could not send the prompt");
      if (result.status === 503 && result.retryAfter) {
        message = `${message} (retry after ${result.retryAfter}s)`;
      }
      showBanner(message);
      return;
    }
    ui.prompt.value = "";
    await refreshSessions();
    await showDesktop(sessionId);
  } finally {
    state.sending = false;
    setBusy(false);
  }
});

ui.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ui.promptForm.requestSubmit();
  }
});

refreshSessions();
setInterval(refreshSessions, 4000);
