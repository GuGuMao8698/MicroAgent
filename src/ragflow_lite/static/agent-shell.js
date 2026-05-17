/* MicroRAG Agent Shell — minimal demo behavior */

(async function () {
  "use strict";

  const API_PREFIX = "/api/v0/agent";
  const LOCAL_ACTIVITY_TTL_MS = 4000;
  const MAX_VISIBLE_ACTIVITIES = 5;

  // ── DOM refs ──

  const sessionList = document.getElementById("session-list");
  const chatArea = document.getElementById("chat-area");
  const composerInput = document.getElementById("composer-input");
  const btnSend = document.getElementById("btn-send");
  const btnNew = document.getElementById("btn-new");

  let activeSessionId = null;
  let commandSummaries = [];
  let localActivitiesBySession = Object.create(null);
  let activityPollTimer = null;
  let commandRefreshTimer = null;
  let commandRefreshAttempts = 0;

  // ── Helpers ──

  async function api(path, options) {
    const resp = await fetch(API_PREFIX + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!resp.ok) {
      throw new Error("Request failed with status " + resp.status);
    }
    if (resp.status === 204) {
      return {};
    }
    return resp.json();
  }

  function createMsgEl(text, role) {
    const div = document.createElement("div");
    div.className = "msg msg-" + role;
    div.textContent = text;
    return div;
  }

  function renderEmpty() {
    chatArea.innerHTML =
      '<div class="chat-empty">Select or create a session to begin.</div>';
  }

  function clearChat() {
    chatArea.innerHTML = '<div class="messages" id="messages"></div>';
  }

  function appendMessage(text, role) {
    let container = document.getElementById("messages");
    if (!container) {
      clearChat();
      container = document.getElementById("messages");
    }
    container.appendChild(createMsgEl(text, role));
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  function showStatus(text) {
    let el = document.getElementById("runtime-status");
    if (!el) {
      el = document.createElement("div");
      el.id = "runtime-status";
      el.className = "runtime-status";
      chatArea.parentElement.insertBefore(el, chatArea.nextSibling);
    }
    el.textContent = text;
  }

  function clearStatus() {
    const el = document.getElementById("runtime-status");
    if (el) el.textContent = "";
  }

  function getLocalActivities(sessionId) {
    if (!sessionId) return [];
    return localActivitiesBySession[sessionId] || [];
  }

  function renderCurrentSessionActivities(sessionId, runtimeActivities) {
    if (!sessionId || sessionId !== activeSessionId) return;
    const localActivities = pruneLocalActivities(sessionId, runtimeActivities);
    renderActivityStream([...localActivities, ...runtimeActivities]);
  }

  function stopActivityPolling() {
    if (activityPollTimer !== null) {
      clearInterval(activityPollTimer);
      activityPollTimer = null;
    }
  }

  function stopCommandRefresh() {
    if (commandRefreshTimer !== null) {
      clearTimeout(commandRefreshTimer);
      commandRefreshTimer = null;
    }
    commandRefreshAttempts = 0;
  }

  function scheduleCommandRefresh() {
    if (commandSummaries.length > 0 || commandRefreshTimer !== null) return;
    if (commandRefreshAttempts >= 8) return;
    commandRefreshAttempts += 1;
    commandRefreshTimer = window.setTimeout(function () {
      commandRefreshTimer = null;
      loadCommandSummaries().catch(function () {
        scheduleCommandRefresh();
      });
    }, 250);
  }

  function startActivityPolling(sessionId) {
    stopActivityPolling();
    const pollSessionId = sessionId || activeSessionId;
    if (!pollSessionId) return;
    activityPollTimer = window.setInterval(function () {
      loadActivityStream(pollSessionId).catch(function () {
        showStatus("Thinking…");
      });
    }, 650);
  }

  // ── Session list ──

  async function loadSessions() {
    try {
      const sessions = await api("/sessions");
      sessionList.innerHTML = "";
      sessions.forEach(function (s) {
        const li = document.createElement("li");
        li.className = "session-item" + (s.id === activeSessionId ? " active" : "");
        li.dataset.id = s.id;

        const title = document.createElement("span");
        title.className = "session-title";
        title.textContent = s.title || s.id;
        li.appendChild(title);

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "session-delete";
        deleteButton.textContent = "×";
        deleteButton.title = "Delete chat";
        deleteButton.setAttribute("aria-label", "Delete chat");
        deleteButton.addEventListener("click", function (event) {
          event.stopPropagation();
          deleteSession(s.id);
        });
        li.appendChild(deleteButton);

        li.addEventListener("click", function () {
          selectSession(s.id);
        });
        sessionList.appendChild(li);
      });
      return sessions;
    } catch (err) {
      showStatus("Unable to load sessions: " + err.message);
      return [];
    }
  }

  async function deleteSession(id) {
    try {
      stopActivityPolling();
      await api("/sessions/" + id, {
        method: "DELETE",
      });
      delete localActivitiesBySession[id];
      if (activeSessionId === id) {
        activeSessionId = null;
        clearChat();
        await loadSessions();
        await startInitialSession();
      } else {
        await loadSessions();
      }
    } catch (err) {
      showStatus("Unable to delete session: " + err.message);
    }
  }

  async function startInitialSession() {
    const sessions = await loadSessions();
    if (sessions.length > 0) {
      selectSession(sessions[sessions.length - 1].id);
      return;
    }
    showStatus("Starting session…");
    await createSession();
  }

  async function createSession() {
    const session = await api("/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "New chat" }),
    });
    activeSessionId = session.id;
    renderActivityStream([]);
    clearChat();
    clearStatus();
    await loadSessions();
    await loadCommandSummaries();
    composerInput.focus();
  }

  async function selectSession(id) {
    stopActivityPolling();
    activeSessionId = id;
    clearChat();
    clearStatus();
    await loadSessions();
    await loadActivityStream(id);
    composerInput.focus();
  }

  // ── Slash picker & activity stream ──

  async function loadCommandSummaries() {
    const data = await api("/commands");
    commandSummaries = Array.isArray(data.commands) ? data.commands : [];
    renderSlashPicker();
    if (commandSummaries.length === 0) {
      scheduleCommandRefresh();
    } else {
      stopCommandRefresh();
    }
  }

  async function loadActivityStream(sessionId) {
    const requestedSessionId = sessionId || activeSessionId;
    if (!requestedSessionId) {
      renderActivityStream([]);
      return;
    }
    const data = await api("/sessions/" + requestedSessionId + "/activity");
    const runtimeActivities = Array.isArray(data.activities) ? data.activities : [];
    if (requestedSessionId !== activeSessionId) return;
    renderCurrentSessionActivities(requestedSessionId, runtimeActivities);
  }

  async function refreshActivityStreamBestEffort() {
    await loadActivityStream().catch(function () {
      showStatus("Thinking…");
    });
  }

  function renderSlashPicker() {
    const picker = document.getElementById("slash-picker");
    const input = document.getElementById("composer-input");
    if (!picker || !input) return;
    const value = input.value.trimStart();
    if (!value.startsWith("/")) {
      picker.hidden = true;
      picker.replaceChildren();
      return;
    }
    const query = value.slice(1).toLowerCase();
    const matches = commandSummaries
      .filter(function (c) { return c.name.toLowerCase().startsWith(query); })
      .slice(0, 8);
    if (matches.length === 0) {
      picker.hidden = true;
      picker.replaceChildren();
      return;
    }
    picker.hidden = false;
    picker.replaceChildren(...matches.map(function (c) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "slash-picker-item";
      btn.innerHTML = "<strong>/" + esc(c.name) + "</strong><span>" + esc(c.description || "") + "</span>";
      btn.addEventListener("click", function () { selectSlashCommand(c); });
      return btn;
    }));
  }

  function onComposerInput() {
    const value = composerInput.value.trimStart();
    if (value.startsWith("/") && commandSummaries.length === 0) {
      loadCommandSummaries().catch(function () {
        scheduleCommandRefresh();
      });
    }
    renderSlashPicker();
  }

  function selectSlashCommand(command) {
    const input = document.getElementById("composer-input");
    if (!input) return;
    input.value = "/" + command.name + " ";
    input.focus();
    renderSlashPicker();
  }

  function addLocalActivity(activity) {
    if (!activeSessionId) return;
    const now = new Date().toISOString();
    const localActivities = [
      {
        activity_id: "local-" + now + "-" + activity.kind,
        created_at: now,
        updated_at: now,
        expires_at: Date.now() + LOCAL_ACTIVITY_TTL_MS,
        ...activity,
      },
      ...getLocalActivities(activeSessionId),
    ].slice(0, 10);
    localActivitiesBySession[activeSessionId] = localActivities;
    renderCurrentSessionActivities(activeSessionId, []);
  }

  function pruneLocalActivities(sessionId, runtimeActivities) {
    const localActivities = getLocalActivities(sessionId);
    const now = Date.now();
    const hasRuntimeActivity = Array.isArray(runtimeActivities) && runtimeActivities.length > 0;
    const next = localActivities.filter(function (activity) {
      if (activity.kind === "command" && hasRuntimeActivity) return false;
      if (activity.expires_at && activity.expires_at <= now) return false;
      return true;
    });
    localActivitiesBySession[sessionId] = next;
    return next;
  }

  function renderActivityStream(activities) {
    const stream = document.getElementById("activity-stream");
    if (!stream) return;
    const visible = collapseActivityStream(activities).slice(-MAX_VISIBLE_ACTIVITIES);
    stream.replaceChildren(...visible.map(function (a) {
      const row = document.createElement("div");
      row.className = "activity-row activity-" + a.kind + " activity-" + a.status;
      const summary = a.summary && a.summary !== a.status ? a.summary : "";
      row.innerHTML = '<span class="activity-dot" aria-hidden="true"></span><span class="activity-main"><strong>' + esc(a.label || "Activity") + '</strong><small>' + esc(summary) + '</small></span><span class="activity-status">' + esc(a.status || "") + '</span>';
      return row;
    }));
  }

  function collapseActivityStream(activities) {
    const byKey = new Map();
    activities.forEach(function (activity) {
      const key = activity.source_tool_call_id || activity.activity_id || activity.kind + ":" + activity.label;
      byKey.set(key, activity);
    });
    return Array.from(byKey.values()).sort(function (a, b) {
      return String(a.created_at || "").localeCompare(String(b.created_at || ""));
    });
  }

  function esc(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ── Send message ──

  async function sendMessage() {
    const text = composerInput.value.trim();
    if (!text) return;

    btnSend.disabled = true;
    stopActivityPolling();
    let sendSessionId = null;

    try {
      if (!activeSessionId) {
        showStatus("Starting session…");
        await createSession();
      }

      sendSessionId = activeSessionId;
      composerInput.value = "";
      appendMessage(text, "user");
      showStatus("Thinking…");

      if (text.trimStart().startsWith("/")) {
        addLocalActivity({
          kind: "command",
          label: text.trimStart().split(/\s+/, 1)[0],
          status: "started",
          summary: "Command submitted to runtime.",
        });
      }

      startActivityPolling(sendSessionId);
      const result = await api("/sessions/" + sendSessionId + "/messages", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });

      if (sendSessionId !== activeSessionId) return;
      await refreshActivityStreamBestEffort();

      if (result.status === "recoverable_error") {
        appendMessage("Error: session encountered an issue. Try resuming.", "assistant");
      } else {
        appendMessage(result.message || "(empty reply)", "assistant");
      }
    } catch (err) {
      if (sendSessionId === activeSessionId) {
        appendMessage("Network error: " + err.message, "assistant");
      }
    } finally {
      stopActivityPolling();
      btnSend.disabled = false;
      if (!sendSessionId || sendSessionId === activeSessionId) {
        clearStatus();
        composerInput.focus();
      }
    }
  }

  // ── Event binding ──

  btnNew.addEventListener("click", createSession);
  btnSend.addEventListener("click", sendMessage);
  composerInput?.addEventListener("input", onComposerInput);
  composerInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── Init ──

  renderEmpty();
  try {
    await startInitialSession();
    await loadCommandSummaries();
  } catch (err) {
    showStatus("Unable to start session: " + err.message);
  }
})();
