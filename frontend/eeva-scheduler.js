/**
 * <eeva-scheduler> — drop-in chat widget for booking meetings through Eeva.
 *
 *   <script type="module" src="/eeva-scheduler.js"></script>
 *   <eeva-scheduler api-url="https://xxxx.execute-api.us-west-2.amazonaws.com/chat"
 *                   owner-name="Shubhankar"></eeva-scheduler>
 *
 * Attributes:
 *   api-url     (required) the ChatEndpoint output of the SAM stack
 *   owner-name  name used in the greeting (default "Shubhankar")
 *   inline      render the chat in the page flow instead of a floating bubble
 *   theme       "light" | "dark" (default follows the visitor's OS setting)
 *
 * Fires a bubbling `eeva:booked` event with the booking in `event.detail`.
 * Style hooks: --eeva-accent, --eeva-accent-text, --eeva-font, --eeva-radius.
 */

const MAX_CHARS = 2000;

const STYLES = `
:host {
  --accent: var(--eeva-accent, #4f46e5);
  --accent-text: var(--eeva-accent-text, #ffffff);
  --radius: var(--eeva-radius, 16px);
  --bg: #ffffff;
  --surface: #f4f4f6;
  --text: #1a1a1f;
  --muted: #6b6b76;
  --border: #e3e3e8;
  --error: #b42318;
  font-family: var(--eeva-font, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  color: var(--text);
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"])) {
    --bg: #17171c; --surface: #24242b; --text: #ececf1; --muted: #a0a0ab; --border: #33333c; --error: #f97066;
  }
}
:host([theme="dark"]) {
  --bg: #17171c; --surface: #24242b; --text: #ececf1; --muted: #a0a0ab; --border: #33333c; --error: #f97066;
}
* { box-sizing: border-box; }
.launcher {
  position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
  display: flex; align-items: center; gap: 8px;
  padding: 12px 18px; border: 0; border-radius: 999px; cursor: pointer;
  background: var(--accent); color: var(--accent-text);
  font-family: inherit; font-size: 15px; font-weight: 600; line-height: 1;
  box-shadow: 0 6px 24px rgba(0,0,0,.18);
}
.launcher:focus-visible, button:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.panel {
  display: flex; flex-direction: column;
  width: 380px; height: 560px; max-height: calc(100vh - 110px);
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: 0 12px 48px rgba(0,0,0,.22); overflow: hidden;
}
.floating .panel { position: fixed; right: 20px; bottom: 84px; z-index: 2147483000; }
.inline .panel { position: relative; width: 100%; max-width: 560px; height: 600px; max-height: none; box-shadow: none; }
.floating:not(.open) .panel { display: none; }
.inline .launcher { display: none; }
@media (max-width: 480px) {
  .floating .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; max-height: none; border-radius: 0; }
  .floating.open .launcher { display: none; }
}
header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid var(--border);
}
header .title { font-weight: 650; font-size: 15px; }
header .subtitle { font-size: 12px; color: var(--muted); margin-top: 2px; }
.close { background: none; border: 0; color: var(--muted); font-size: 22px; line-height: 1; cursor: pointer; padding: 4px 8px; border-radius: 8px; }
.inline .close { display: none; }
.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.msg { max-width: 85%; padding: 10px 13px; border-radius: 14px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
.msg.assistant { align-self: flex-start; background: var(--surface); border-bottom-left-radius: 4px; }
.msg.user { align-self: flex-end; background: var(--accent); color: var(--accent-text); border-bottom-right-radius: 4px; }
.msg.error { align-self: flex-start; color: var(--error); background: none; padding: 0 4px; font-size: 13px; }
.msg a { color: inherit; }
.msg.booked { border: 1px solid var(--accent); }
.typing { align-self: flex-start; color: var(--muted); font-size: 13px; padding: 0 4px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 16px 12px; }
.suggestions[hidden] { display: none; }
.suggestions button {
  border: 1px solid var(--border); background: var(--bg); color: var(--text);
  border-radius: 999px; padding: 7px 12px; font: inherit; font-size: 13px; cursor: pointer;
}
.suggestions button:hover { border-color: var(--accent); }
form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--border); }
textarea {
  flex: 1; resize: none; min-height: 40px; max-height: 120px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 12px; background: var(--bg); color: var(--text);
  font: inherit; font-size: 14px;
}
.send {
  border: 0; border-radius: 12px; padding: 0 16px; cursor: pointer;
  background: var(--accent); color: var(--accent-text); font: inherit; font-weight: 600; font-size: 14px;
}
.send:disabled { opacity: .5; cursor: default; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
`;

class EevaScheduler extends HTMLElement {
  constructor() {
    super();
    this.history = [];
    this.pending = false;
    this.attachShadow({ mode: "open" });
  }

  get ownerName() {
    return this.getAttribute("owner-name") || "Shubhankar";
  }

  connectedCallback() {
    if (this.root) return;
    const owner = this.ownerName;
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="wrap ${this.hasAttribute("inline") ? "inline" : "floating"}">
        <button class="launcher" type="button" aria-expanded="false" aria-controls="eeva-panel">
          <span aria-hidden="true">📅</span> Book a meeting
        </button>
        <section class="panel" id="eeva-panel" role="dialog" aria-label="Schedule a meeting with ${escapeHtml(owner)}">
          <header>
            <div>
              <div class="title">Eeva</div>
              <div class="subtitle">Schedule time with ${escapeHtml(owner)}</div>
            </div>
            <button class="close" type="button" aria-label="Close">×</button>
          </header>
          <div class="log" role="log" aria-live="polite"></div>
          <div class="suggestions"></div>
          <form>
            <label class="sr-only" for="eeva-input">Message</label>
            <textarea id="eeva-input" rows="1" maxlength="${MAX_CHARS}" placeholder="When would you like to meet?"></textarea>
            <button class="send" type="submit">Send</button>
          </form>
        </section>
      </div>`;

    const $ = (sel) => this.shadowRoot.querySelector(sel);
    this.root = $(".wrap");
    this.log = $(".log");
    this.input = $("textarea");
    this.sendButton = $(".send");
    this.suggestions = $(".suggestions");
    this.launcher = $(".launcher");

    this.launcher.addEventListener("click", () => this.toggle(true));
    $(".close").addEventListener("click", () => this.toggle(false));
    this.root.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.hasAttribute("inline")) this.toggle(false);
    });
    $("form").addEventListener("submit", (e) => {
      e.preventDefault();
      this.send(this.input.value);
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        this.send(this.input.value);
      }
    });
    this.input.addEventListener("input", () => this.autosize());

    this.addAssistant(
      `Hi! I'm Eeva, ${owner}'s scheduling assistant. I can find a time that works for you and send a calendar invite. When would you like to meet?`
    );
    for (const text of [
      "Book a 30-minute chat this week",
      `When is ${owner} free next week?`,
      "I'd like to talk about a project",
    ]) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.addEventListener("click", () => this.send(text));
      this.suggestions.append(b);
    }
    if (this.hasAttribute("open")) this.toggle(true);
  }

  toggle(open) {
    this.root.classList.toggle("open", open);
    this.launcher.setAttribute("aria-expanded", String(open));
    if (open) this.input.focus();
    else this.launcher.focus();
  }

  autosize() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 120)}px`;
  }

  addBubble(role, text, extraClass) {
    const div = document.createElement("div");
    div.className = `msg ${role}${extraClass ? " " + extraClass : ""}`;
    if (role === "assistant") appendLinkified(div, text);
    else div.textContent = text;
    this.log.append(div);
    this.log.scrollTop = this.log.scrollHeight;
    return div;
  }

  addAssistant(text, extraClass) {
    this.history.push({ role: "assistant", content: text });
    return this.addBubble("assistant", text, extraClass);
  }

  async send(raw) {
    const text = raw.trim().slice(0, MAX_CHARS);
    if (!text || this.pending) return;
    const apiUrl = this.getAttribute("api-url");
    if (!apiUrl) {
      this.addBubble("error", "Eeva isn't configured yet (missing api-url).");
      return;
    }

    this.suggestions.hidden = true;
    this.log.querySelectorAll(".msg.error").forEach((el) => el.remove());
    this.input.value = "";
    this.autosize();
    this.history.push({ role: "user", content: text });
    const userBubble = this.addBubble("user", text);
    this.setPending(true);

    try {
      const res = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: this.history,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Server unavailable — please try again.");

      this.addAssistant(data.reply, data.booking ? "booked" : "");
      if (data.booking) {
        this.dispatchEvent(new CustomEvent("eeva:booked", { detail: data.booking, bubbles: true, composed: true }));
      }
    } catch (err) {
      // Roll back so the visitor can simply resend.
      this.history.pop();
      userBubble.remove();
      this.input.value = text;
      this.autosize();
      const message = err instanceof TypeError ? "Server unavailable — please try again." : err.message;
      this.addBubble("error", message);
    } finally {
      this.setPending(false);
      this.input.focus();
    }
  }

  setPending(pending) {
    this.pending = pending;
    this.sendButton.disabled = pending;
    if (pending) {
      this.typing = document.createElement("div");
      this.typing.className = "typing";
      this.typing.textContent = "Eeva is thinking…";
      this.log.append(this.typing);
      this.log.scrollTop = this.log.scrollHeight;
    } else {
      this.typing?.remove();
    }
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Append text to el, turning https:// URLs into links. Never uses innerHTML. */
function appendLinkified(el, text) {
  const urlPattern = /https:\/\/[^\s<>"')]+/g;
  let last = 0;
  for (const match of text.matchAll(urlPattern)) {
    el.append(text.slice(last, match.index));
    const a = document.createElement("a");
    a.href = match[0];
    a.textContent = match[0];
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    el.append(a);
    last = match.index + match[0].length;
  }
  el.append(text.slice(last));
}

if (!customElements.get("eeva-scheduler")) {
  customElements.define("eeva-scheduler", EevaScheduler);
}
