/* MicroRAG Agent Shell — minimal demo behavior */

(async function () {
  "use strict";

  const API_PREFIX = "/api/v0/agent";

  // ── DOM refs ──

  const sessionList = document.getElementById("session-list");
  const chatArea = document.getElementById("chat-area");
  const composerInput = document.getElementById("composer-input");
  const btnSend = document.getElementById("btn-send");
  const btnNew = document.getElementById("btn-new");

  let activeSessionId = null;

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
      await api("/sessions/" + id, {
        method: "DELETE",
      });
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
    clearChat();
    clearStatus();
    await loadSessions();
    composerInput.focus();
  }

  async function selectSession(id) {
    activeSessionId = id;
    clearChat();
    clearStatus();
    await loadSessions();
    composerInput.focus();
  }

  // ── Send message ──

  async function sendMessage() {
    const text = composerInput.value.trim();
    if (!text) return;

    btnSend.disabled = true;

    try {
      if (!activeSessionId) {
        showStatus("Starting session…");
        await createSession();
      }

      composerInput.value = "";
      appendMessage(text, "user");
      showStatus("Thinking…");

      const result = await api("/sessions/" + activeSessionId + "/messages", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });

      if (result.status === "recoverable_error") {
        appendMessage("Error: session encountered an issue. Try resuming.", "assistant");
      } else {
        appendMessage(result.message || "(empty reply)", "assistant");
      }
    } catch (err) {
      appendMessage("Network error: " + err.message, "assistant");
    } finally {
      btnSend.disabled = false;
      clearStatus();
      composerInput.focus();
    }
  }

  // ── Event binding ──

  btnNew.addEventListener("click", createSession);
  btnSend.addEventListener("click", sendMessage);
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
  } catch (err) {
    showStatus("Unable to start session: " + err.message);
  }
})();
