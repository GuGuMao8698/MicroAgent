"""UI route serving the MicroRAG agent demo shell HTML page.

This module provides a single GET /agent endpoint that returns the
inline HTML shell. Static assets (CSS/JS) are served via the
StaticFiles mount in app.py.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

_SHELL_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MicroRAG</title>
<link rel="stylesheet" href="/static/agent-shell.css">
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>MicroRAG</h1>
      <button id="btn-new" class="btn-new">New</button>
    </div>
    <ul id="session-list" class="session-list"></ul>
  </aside>
  <div class="main">
    <div id="chat-area" class="chat-area"></div>
    <div id="activity-stream" class="activity-stream" aria-live="polite"></div>
    <div id="composer-toolbar" class="composer-toolbar">
      <div id="slash-picker" class="slash-picker" hidden></div>
      <form class="composer" onsubmit="return false">
        <input id="composer-input" type="text"
               placeholder="Type a message…" autocomplete="off">
        <button id="btn-send" class="btn-send">Send</button>
      </form>
    </div>
  </div>
</div>
<script src="/static/agent-shell.js"></script>
</body>
</html>
"""


@router.get("/agent", response_class=HTMLResponse)
def agent_shell() -> str:
    """Serve the MicroRAG agent demo shell."""
    return _SHELL_HTML
