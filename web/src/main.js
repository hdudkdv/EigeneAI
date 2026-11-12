import "@fontsource/fraunces/500.css";
import "@fontsource/fraunces/700.css";
import "@fontsource/source-sans-3/400.css";
import "@fontsource/source-sans-3/600.css";
import "@fontsource/source-sans-3/700.css";
import "./styles.css";
import { api, setBaseUrl, getBaseUrl, streamChat } from "./api.js";

const STORAGE_TOKEN = "eigeneai.token";
const STORAGE_URL = "eigeneai.serverUrl";
const STORAGE_NAME = "eigeneai.name";

const app = document.getElementById("app");

const state = {
  token: localStorage.getItem(STORAGE_TOKEN) || "",
  name: localStorage.getItem(STORAGE_NAME) || "",
  serverUrl: localStorage.getItem(STORAGE_URL) || "",
  me: null,
  chats: [],
  activeChatId: null,
  messages: [],
  health: null,
  busy: false,
  offline: false,
  queueHint: "",
  error: "",
  loginTab: "token",
};

if (state.serverUrl) setBaseUrl(state.serverUrl);

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function refreshHealth() {
  try {
    state.health = await api("/health");
    state.offline = false;
  } catch {
    state.health = null;
    state.offline = true;
  }
}

async function bootstrapSession() {
  if (!state.token) return false;
  try {
    state.me = await api("/api/me", { token: state.token });
    state.name = state.me.name;
    localStorage.setItem(STORAGE_NAME, state.name);
    await loadChats();
    return true;
  } catch {
    state.token = "";
    localStorage.removeItem(STORAGE_TOKEN);
    return false;
  }
}

async function loadChats() {
  const data = await api("/api/chats", { token: state.token });
  state.chats = data.chats || [];
  if (!state.activeChatId && state.chats[0]) {
    state.activeChatId = state.chats[0].id;
  }
  if (state.activeChatId) {
    await loadMessages(state.activeChatId);
  } else {
    state.messages = [];
  }
}

async function loadMessages(chatId) {
  const data = await api(`/api/chats/${chatId}`, { token: state.token });
  state.messages = data.messages || [];
}

function saveSession({ token, name, serverUrl }) {
  if (serverUrl != null) {
    state.serverUrl = serverUrl;
    localStorage.setItem(STORAGE_URL, serverUrl);
    setBaseUrl(serverUrl);
  }
  if (token) {
    state.token = token;
    localStorage.setItem(STORAGE_TOKEN, token);
  }
  if (name) {
    state.name = name;
    localStorage.setItem(STORAGE_NAME, name);
  }
}

function logout() {
  state.token = "";
  state.me = null;
  state.chats = [];
  state.messages = [];
  state.activeChatId = null;
  localStorage.removeItem(STORAGE_TOKEN);
  render();
}

function renderLogin() {
  app.innerHTML = "";
  const panel = el(`
    <div class="login">
      <div class="login-panel">
        <h1 class="brand">EigeneAI</h1>
        <p class="tagline">Privater Familien-Chat auf eurer lokalen Appliance — ohne Cloud-LLM.</p>
        <div class="tabs">
          <button type="button" data-tab="token" class="${state.loginTab === "token" ? "active" : ""}">Token</button>
          <button type="button" data-tab="invite" class="${state.loginTab === "invite" ? "active" : ""}">Einladung</button>
        </div>
        <label for="serverUrl">Server-URL (LAN)</label>
        <input id="serverUrl" placeholder="https://eigeneai.local oder leer = dieser Host" value="${escapeHtml(state.serverUrl)}" />
        <div id="login-fields"></div>
        <div class="login-actions">
          <button type="button" id="login-submit">Anmelden</button>
        </div>
        <p class="hint">Tipp: Auf dem iPhone „Zum Home-Bildschirm“ für die PWA. Selbstsigniertes Zertifikat einmal im Browser akzeptieren.</p>
        <p class="error" id="login-error">${escapeHtml(state.error)}</p>
      </div>
    </div>
  `);
  app.appendChild(panel);

  const fields = panel.querySelector("#login-fields");
  function drawFields() {
    if (state.loginTab === "invite") {
      fields.innerHTML = `
        <label for="invite">Einladungscode</label>
        <input id="invite" autocomplete="off" />
        <label for="name">Dein Name</label>
        <input id="name" autocomplete="nickname" />
      `;
    } else {
      fields.innerHTML = `
        <label for="token">Account-Token</label>
        <input id="token" autocomplete="off" placeholder="eai_…" value="" />
      `;
    }
  }
  drawFields();

  panel.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.loginTab = btn.dataset.tab;
      state.error = "";
      renderLogin();
    });
  });

  panel.querySelector("#login-submit").addEventListener("click", async () => {
    state.error = "";
    const serverUrl = panel.querySelector("#serverUrl").value.trim();
    saveSession({ serverUrl });
    try {
      if (state.loginTab === "invite") {
        const code = panel.querySelector("#invite").value.trim();
        const name = panel.querySelector("#name").value.trim();
        if (!code || !name) throw new Error("Einladungscode und Name sind nötig.");
        const res = await api("/api/auth/redeem", {
          method: "POST",
          body: { code, name },
        });
        saveSession({ token: res.token, name: res.name });
      } else {
        const token = panel.querySelector("#token").value.trim();
        if (!token) throw new Error("Bitte Token eingeben.");
        saveSession({ token });
        const me = await api("/api/me", { token });
        saveSession({ name: me.name });
      }
      await bootstrapSession();
      await refreshHealth();
      render();
    } catch (err) {
      state.error = err.message || "Anmeldung fehlgeschlagen";
      renderLogin();
    }
  });
}

function renderShell() {
  const model = state.health?.default_model || "Modell unbekannt";
  const online = !state.offline && state.health;
  app.innerHTML = "";
  const shell = el(`
    <div class="shell">
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-top">
          <h1>EigeneAI</h1>
          <button type="button" class="ghost" id="close-sidebar">Schließen</button>
        </div>
        <p class="meta">Angemeldet als ${escapeHtml(state.name || state.me?.name || "—")}</p>
        <button type="button" id="new-chat">Neuer Chat</button>
        <ul class="chat-list" id="chat-list"></ul>
        <button type="button" class="secondary" id="logout">Abmelden</button>
      </aside>
      <section class="main">
        <header class="topbar">
          <button type="button" class="ghost" id="open-sidebar">Chats</button>
          <div class="status-pill">
            <span class="status-dot ${online ? "" : "down"}"></span>
            <span>${online ? escapeHtml(model) : "Server unerreichbar"}</span>
          </div>
          <span class="meta">${escapeHtml(getBaseUrl() || location.origin)}</span>
        </header>
        <div id="banner-slot"></div>
        <div class="messages" id="messages"></div>
        <form class="composer" id="composer">
          <textarea id="prompt" rows="2" placeholder="Nachricht schreiben…" ${state.busy ? "disabled" : ""}></textarea>
          <button type="submit" ${state.busy ? "disabled" : ""}>${state.busy ? "…" : "Senden"}</button>
        </form>
      </section>
    </div>
  `);
  app.appendChild(shell);

  const list = shell.querySelector("#chat-list");
  state.chats.forEach((c) => {
    const item = el(`
      <li>
        <button type="button" class="${c.id === state.activeChatId ? "active" : ""}" data-id="${c.id}">
          ${escapeHtml(c.title || "Chat")}
        </button>
      </li>
    `);
    item.querySelector("button").addEventListener("click", async () => {
      state.activeChatId = c.id;
      await loadMessages(c.id);
      render();
    });
    list.appendChild(item);
  });

  const bannerSlot = shell.querySelector("#banner-slot");
  if (state.offline) {
    bannerSlot.appendChild(
      el(`<div class="banner danger">Server unerreichbar. Prüfe LAN-URL und Zertifikat.</div>`),
    );
  } else if (state.queueHint) {
    bannerSlot.appendChild(el(`<div class="banner">${escapeHtml(state.queueHint)}</div>`));
  } else if (state.health?.mock_inference) {
    bannerSlot.appendChild(
      el(`<div class="banner">Mock-Inference aktiv (keine echte MI50). Für Produktion llama.cpp + ROCm 6.3.3.</div>`),
    );
  }

  const messagesEl = shell.querySelector("#messages");
  if (!state.messages.length) {
    messagesEl.appendChild(
      el(`<div class="empty">Noch keine Nachrichten. Frag etwas — die Antworten bleiben auf eurem Server.</div>`),
    );
  } else {
    state.messages.forEach((m) => {
      messagesEl.appendChild(
        el(`
          <div class="bubble ${m.role}">
            <span class="who">${m.role === "user" ? "Du" : "EigeneAI"}</span>
            ${escapeHtml(m.content)}
          </div>
        `),
      );
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  shell.querySelector("#logout").addEventListener("click", logout);
  shell.querySelector("#open-sidebar").addEventListener("click", () => {
    shell.querySelector("#sidebar").classList.add("open");
  });
  shell.querySelector("#close-sidebar").addEventListener("click", () => {
    shell.querySelector("#sidebar").classList.remove("open");
  });
  shell.querySelector("#new-chat").addEventListener("click", async () => {
    const chat = await api("/api/chats", {
      method: "POST",
      token: state.token,
      body: { title: "Neuer Chat" },
    });
    state.chats.unshift(chat);
    state.activeChatId = chat.id;
    state.messages = [];
    render();
  });

  shell.querySelector("#composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const textarea = shell.querySelector("#prompt");
    const text = textarea.value.trim();
    if (!text || state.busy) return;
    await sendMessage(text);
  });
}

async function sendMessage(text) {
  state.busy = true;
  state.queueHint = "";
  state.error = "";

  if (!state.activeChatId) {
    const chat = await api("/api/chats", {
      method: "POST",
      token: state.token,
      body: { title: text.slice(0, 48) },
    });
    state.chats.unshift(chat);
    state.activeChatId = chat.id;
  }

  state.messages.push({ role: "user", content: text });
  state.messages.push({ role: "assistant", content: "" });
  render();

  const history = state.messages
    .slice(0, -1)
    .map((m) => ({ role: m.role, content: m.content }));

  try {
    await streamChat({
      token: state.token,
      chatId: state.activeChatId,
      messages: history,
      onMeta: (meta) => {
        if (meta?.hint) {
          state.queueHint = meta.hint;
          render();
        }
      },
      onToken: (piece) => {
        const last = state.messages[state.messages.length - 1];
        last.content += piece;
        const node = document.querySelector(".messages .bubble.assistant:last-child");
        if (node) {
          node.childNodes[node.childNodes.length - 1].textContent = last.content;
          node.parentElement.scrollTop = node.parentElement.scrollHeight;
        }
      },
    });
    await loadChats();
  } catch (err) {
    state.queueHint = "";
    const last = state.messages[state.messages.length - 1];
    if (last?.role === "assistant" && !last.content) {
      last.content = `Fehler: ${err.message}`;
    }
  } finally {
    state.busy = false;
    state.queueHint = "";
    render();
  }
}

function render() {
  if (!state.token) {
    renderLogin();
    return;
  }
  renderShell();
}

async function start() {
  await refreshHealth();
  if (state.token) {
    const ok = await bootstrapSession();
    if (!ok) {
      renderLogin();
      return;
    }
  }
  render();
  setInterval(refreshHealth, 15000);
}

start();
