/**
 * MCDU configuration panel (custom sidebar panel).
 *
 * Self-contained web component, no build step. Talks to the integration via
 * the HA WebSocket API (mcdu/devices, mcdu/pages/get, mcdu/pages/save,
 * mcdu/preview). The preview is rendered by the SAME PageEngine that drives
 * the hardware, so what you see is what the display shows.
 */

const COLORS = ["white", "amber", "cyan", "green", "magenta", "red", "yellow", "grey", "blue"];
const COLOR_HEX = {
  white: "#e8e8e8",
  amber: "#ffb400",
  cyan: "#00d5d5",
  green: "#22cc44",
  magenta: "#e858e8",
  red: "#ff3333",
  yellow: "#ffe14d",
  grey: "#8a8a8a",
  blue: "#00d5d5",
};
const SLOT_ROWS = [3, 5, 7, 9, 11, 13];

const EMPTY_SIDE = () => ({
  label: "",
  display: { type: "empty", text: "", colLabel: "", colData: "", source: "", format: "", unit: "" },
  button: { type: "empty", target: "" },
});

class McduPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._devices = [];
    this._entryId = null;
    this._pages = [];
    this._selectedPageId = null;
    this._dirty = false;
    this._previewLines = null;
    this._previewOffset = 0;
    this._previewTotal = 1;
    this._previewTimer = null;
    this._initialized = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._loadDevices();
    }
  }

  set narrow(_v) {}
  set panel(_v) {}

  async _loadDevices() {
    try {
      this._devices = await this._hass.callWS({ type: "mcdu/devices" });
      if (this._devices.length && !this._entryId) {
        this._entryId = this._devices[0].entry_id;
        await this._loadPages();
      }
      this._render();
    } catch (err) {
      this._renderError(`Failed to load devices: ${err.message || err.code}`);
    }
  }

  async _loadPages() {
    const result = await this._hass.callWS({ type: "mcdu/pages/get", entry_id: this._entryId });
    this._pages = JSON.parse(JSON.stringify(result.pages || []));
    this._selectedPageId = result.current_page || (this._pages[0] && this._pages[0].id) || null;
    this._dirty = false;
    this._previewOffset = 0;
    this._schedulePreview();
  }

  async _save() {
    try {
      await this._hass.callWS({ type: "mcdu/pages/save", entry_id: this._entryId, pages: this._pages });
      this._dirty = false;
      this._render();
    } catch (err) {
      alert(`Save failed: ${err.message || err.code}`);
    }
  }

  _schedulePreview() {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => this._fetchPreview(), 250);
  }

  async _fetchPreview() {
    if (!this._entryId || !this._selectedPageId) return;
    try {
      const result = await this._hass.callWS({
        type: "mcdu/preview",
        entry_id: this._entryId,
        page_id: this._selectedPageId,
        pages: this._pages,
        page_offset: this._previewOffset,
      });
      this._previewLines = result.lines;
      this._previewTotal = result.total_pages;
      this._previewOffset = result.page_offset;
    } catch (err) {
      this._previewLines = null;
    }
    this._render();
  }

  // ---- data helpers -------------------------------------------------

  _page() {
    return this._pages.find((p) => p.id === this._selectedPageId) || null;
  }

  _line(row) {
    const page = this._page();
    if (!page) return null;
    if (!page.lines) page.lines = [];
    let line = page.lines.find((l) => l.row === row);
    if (!line) {
      line = { row, left: EMPTY_SIDE(), right: EMPTY_SIDE() };
      page.lines.push(line);
      page.lines.sort((a, b) => a.row - b.row);
    }
    if (!line.left) line.left = EMPTY_SIDE();
    if (!line.right) line.right = EMPTY_SIDE();
    if (!line.left.display) line.left.display = EMPTY_SIDE().display;
    if (!line.left.button) line.left.button = EMPTY_SIDE().button;
    if (!line.right.display) line.right.display = EMPTY_SIDE().display;
    if (!line.right.button) line.right.button = EMPTY_SIDE().button;
    return line;
  }

  _touch() {
    this._dirty = true;
    this._syncDisplayTypes();
    this._schedulePreview();
    this._render();
  }

  _syncDisplayTypes() {
    const page = this._page();
    if (!page || !page.lines) return;
    for (const line of page.lines) {
      for (const side of ["left", "right"]) {
        const d = line[side] && line[side].display;
        if (!d) continue;
        d.type = d.source ? "datapoint" : d.text ? "label" : "empty";
      }
    }
  }

  _addPage() {
    let n = this._pages.length + 1;
    let id = `page-${n}`;
    while (this._pages.some((p) => p.id === id)) id = `page-${++n}`;
    this._pages.push({ id, name: `PAGE ${n}`, parent: this._selectedPageId || null, lines: [] });
    this._selectedPageId = id;
    this._touch();
  }

  _deletePage() {
    const page = this._page();
    if (!page) return;
    if (!confirm(`Delete page "${page.name || page.id}"?`)) return;
    this._pages = this._pages.filter((p) => p.id !== page.id);
    for (const p of this._pages) {
      if (p.parent === page.id) p.parent = null;
    }
    this._selectedPageId = this._pages[0] ? this._pages[0].id : null;
    this._touch();
  }

  _entityOptions() {
    if (!this._hass) return "";
    return Object.keys(this._hass.states)
      .sort()
      .map((id) => `<option value="${id}"></option>`)
      .join("");
  }

  // ---- rendering ----------------------------------------------------

  _renderError(message) {
    this.shadowRoot.innerHTML = `<p style="padding:24px;color:var(--error-color,#c62828)">${message}</p>`;
  }

  _render() {
    const style = `
      <style>
        :host { display:block; height:100%; overflow:auto;
                background: var(--primary-background-color); color: var(--primary-text-color);
                font-family: var(--paper-font-body1_-_font-family, sans-serif); }
        .layout { display:flex; gap:16px; padding:16px; flex-wrap:wrap; align-items:flex-start; }
        .card { background: var(--card-background-color); border-radius: 12px;
                box-shadow: var(--ha-card-box-shadow, 0 1px 4px rgba(0,0,0,.2)); padding:16px; }
        .sidebar { width: 230px; flex-shrink:0; }
        .editor { flex: 1; min-width: 460px; }
        .previewbox { width: 460px; flex-shrink:0; position: sticky; top: 16px; }
        h2 { margin: 4px 0 12px; font-size: 18px; }
        h3 { margin: 16px 0 8px; font-size: 14px; opacity:.8; text-transform: uppercase; letter-spacing:.5px; }
        select, input { background: var(--secondary-background-color); color: var(--primary-text-color);
                border: 1px solid var(--divider-color); border-radius: 6px; padding: 5px 7px;
                font-size: 13px; box-sizing: border-box; }
        input:focus, select:focus { outline: 2px solid var(--primary-color); }
        .pagelist { list-style:none; margin:8px 0; padding:0; }
        .pagelist li { padding: 6px 10px; border-radius:6px; cursor:pointer; display:flex; gap:6px; }
        .pagelist li.sel { background: var(--primary-color); color: var(--text-primary-color,#fff); }
        .pagelist li:hover:not(.sel) { background: var(--secondary-background-color); }
        .btn { background: var(--primary-color); color: var(--text-primary-color,#fff);
               border:none; border-radius:8px; padding:8px 16px; font-size:14px; cursor:pointer; }
        .btn[disabled] { opacity:.4; cursor:default; }
        .btn.ghost { background:transparent; color: var(--primary-color); border:1px solid var(--primary-color); }
        .btn.danger { background: var(--error-color,#c62828); }
        .row { display:flex; gap:8px; align-items:center; margin-bottom:8px; flex-wrap:wrap; }
        .slot { border:1px solid var(--divider-color); border-radius:10px; padding:10px 12px; margin-bottom:10px; }
        .slot.highlight { outline: 2px solid var(--primary-color); }
        .slot h4 { margin:0 0 8px; font-size:12px; opacity:.7; }
        .sides { display:grid; grid-template-columns: 1fr 1fr; gap:12px; }
        .side label { display:block; font-size:11px; opacity:.7; margin:6px 0 2px; }
        .side input, .side select { width:100%; }
        .grid2 { display:grid; grid-template-columns: 1fr 1fr; gap:6px; }
        .mcdu { background:#0a0a0a; border-radius:12px; padding:18px 14px; border: 3px solid #333; }
        .mcdu pre { margin:0; font-family:"Courier New",monospace; font-size:15px; line-height:1.5;
                    letter-spacing:1px; cursor:pointer; }
        .toolbar { display:flex; gap:8px; align-items:center; margin-bottom:12px; }
        .dirty { color: var(--warning-color,#ffa600); font-size:12px; }
        .pager { display:flex; gap:8px; justify-content:center; margin-top:8px; }
        .muted { opacity:.6; font-size:12px; }
      </style>`;

    if (!this._devices.length) {
      this.shadowRoot.innerHTML = `${style}<div class="layout"><div class="card">
        <h2>MCDU</h2><p>No MCDU devices configured yet. Add one via Settings → Devices &amp; Services.</p>
      </div></div>`;
      return;
    }

    const page = this._page();
    this.shadowRoot.innerHTML = `${style}
      <datalist id="entities">${this._entityOptions()}</datalist>
      <div class="layout">
        <div class="card sidebar">
          <h2>MCDU</h2>
          <select id="device" style="width:100%">
            ${this._devices
              .map(
                (d) =>
                  `<option value="${d.entry_id}" ${d.entry_id === this._entryId ? "selected" : ""}>
                     ${d.device_id} ${d.online ? "🟢" : "⚪"}</option>`
              )
              .join("")}
          </select>
          <h3>Pages</h3>
          <ul class="pagelist">${this._renderPageTree()}</ul>
          <div class="row">
            <button class="btn ghost" id="addpage">+ Page</button>
            <button class="btn danger" id="delpage" ${page ? "" : "disabled"}>Delete</button>
          </div>
          <div class="toolbar">
            <button class="btn" id="save" ${this._dirty ? "" : "disabled"}>Save &amp; apply</button>
            ${this._dirty ? '<span class="dirty">● unsaved</span>' : ""}
          </div>
        </div>

        <div class="card editor">${page ? this._renderEditor(page) : "<p>Select or create a page.</p>"}</div>

        <div class="card previewbox">
          <h3 style="margin-top:0">Live preview</h3>
          <div class="mcdu">${this._renderPreview()}</div>
          ${
            this._previewTotal > 1
              ? `<div class="pager">
                   <button class="btn ghost" id="prevpg" ${this._previewOffset === 0 ? "disabled" : ""}>▲</button>
                   <span class="muted">${this._previewOffset + 1}/${this._previewTotal}</span>
                   <button class="btn ghost" id="nextpg" ${
                     this._previewOffset >= this._previewTotal - 1 ? "disabled" : ""
                   }>▼</button>
                 </div>`
              : ""
          }
          <p class="muted">Rendered by the live engine — click a row to jump to its editor.</p>
        </div>
      </div>`;

    this._bindEvents();
  }

  _renderPageTree() {
    const roots = this._pages.filter((p) => !p.parent || !this._pages.some((q) => q.id === p.parent));
    const children = (id) => this._pages.filter((p) => p.parent === id);
    const item = (p, depth) => {
      const sel = p.id === this._selectedPageId ? "sel" : "";
      const pad = 10 + depth * 14;
      let html = `<li class="${sel}" data-page="${p.id}" style="padding-left:${pad}px">
        ${depth ? "└ " : ""}${(p.name || p.id).toUpperCase()}</li>`;
      for (const c of children(p.id)) html += item(c, depth + 1);
      return html;
    };
    return roots.map((p) => item(p, 0)).join("");
  }

  _renderEditor(page) {
    const pageOptions = (selected) =>
      `<option value="">—</option>` +
      this._pages
        .filter((p) => p.id !== page.id)
        .map((p) => `<option value="${p.id}" ${p.id === selected ? "selected" : ""}>${p.name || p.id}</option>`)
        .join("");
    const colorOptions = (selected) =>
      `<option value="">default</option>` +
      COLORS.map((c) => `<option ${c === selected ? "selected" : ""}>${c}</option>`).join("");

    const slotHtml = SLOT_ROWS.map((row, i) => {
      const line = page.lines ? page.lines.find((l) => l.row === row) : null;
      const side = (s) => {
        const cfg = (line && line[s]) || EMPTY_SIDE();
        const d = cfg.display || {};
        const b = cfg.button || {};
        return `<div class="side">
          <label>Sub-label (row ${row - 1})</label>
          <input data-f="label" data-row="${row}" data-side="${s}" value="${cfg.label || ""}" maxlength="24">
          <label>Text</label>
          <input data-f="text" data-row="${row}" data-side="${s}" value="${d.text || ""}" maxlength="24">
          <label>Entity (datapoint source)</label>
          <input data-f="source" data-row="${row}" data-side="${s}" value="${d.source || ""}" list="entities">
          <div class="grid2">
            <div><label>Format (%.1f)</label>
              <input data-f="format" data-row="${row}" data-side="${s}" value="${d.format || ""}"></div>
            <div><label>Unit</label>
              <input data-f="unit" data-row="${row}" data-side="${s}" value="${d.unit || ""}"></div>
            <div><label>Label color</label>
              <select data-f="colLabel" data-row="${row}" data-side="${s}">${colorOptions(d.colLabel)}</select></div>
            <div><label>Value color</label>
              <select data-f="colData" data-row="${row}" data-side="${s}">${colorOptions(d.colData)}</select></div>
          </div>
          <label>LSK action</label>
          <select data-f="btnType" data-row="${row}" data-side="${s}">
            <option value="empty" ${!b.type || b.type === "empty" ? "selected" : ""}>— (entity from above)</option>
            <option value="navigation" ${b.type === "navigation" ? "selected" : ""}>Go to page</option>
          </select>
          ${
            b.type === "navigation"
              ? `<label>Target page</label>
                 <select data-f="btnTarget" data-row="${row}" data-side="${s}">${pageOptions(b.target)}</select>`
              : ""
          }
        </div>`;
      };
      return `<div class="slot" id="slot-${row}">
        <h4>LSK${i + 1} — display row ${row}</h4>
        <div class="sides">${side("left")}${side("right")}</div>
      </div>`;
    }).join("");

    return `
      <div class="row">
        <div><label class="muted">Name</label><br>
          <input id="pgname" value="${page.name || ""}" maxlength="24"></div>
        <div><label class="muted">Parent page</label><br>
          <select id="pgparent">${pageOptions(page.parent)}</select></div>
        <div><label class="muted">Status bar color</label><br>
          <select id="pgcolor">${colorOptions(page.pageNameColor)}</select></div>
        <div class="muted" style="align-self:flex-end">id: ${page.id}</div>
      </div>
      ${slotHtml}`;
  }

  _renderPreview() {
    if (!this._previewLines) return `<pre style="color:#666">loading…</pre>`;
    return this._previewLines
      .map((line, i) => {
        let html;
        if (line.segments) {
          html = line.segments
            .map((seg) => `<span style="color:${COLOR_HEX[seg.color] || "#e8e8e8"}">${escapeHtml(seg.text)}</span>`)
            .join("");
        } else {
          html = `<span style="color:${COLOR_HEX[line.color] || "#e8e8e8"}">${escapeHtml(line.text)}</span>`;
        }
        return `<pre data-row="${i + 1}">${html}</pre>`;
      })
      .join("");
  }

  // ---- events -------------------------------------------------------

  _bindEvents() {
    const $ = (sel) => this.shadowRoot.querySelector(sel);
    const $$ = (sel) => this.shadowRoot.querySelectorAll(sel);

    const device = $("#device");
    if (device)
      device.addEventListener("change", async (e) => {
        this._entryId = e.target.value;
        await this._loadPages();
        this._render();
      });

    $$(".pagelist li").forEach((li) =>
      li.addEventListener("click", () => {
        this._selectedPageId = li.dataset.page;
        this._previewOffset = 0;
        this._schedulePreview();
        this._render();
      })
    );

    const addpage = $("#addpage");
    if (addpage) addpage.addEventListener("click", () => this._addPage());
    const delpage = $("#delpage");
    if (delpage) delpage.addEventListener("click", () => this._deletePage());
    const save = $("#save");
    if (save) save.addEventListener("click", () => this._save());

    const bindPageProp = (id, apply) => {
      const el = $(id);
      if (el)
        el.addEventListener("change", (e) => {
          apply(e.target.value);
          this._touch();
        });
    };
    bindPageProp("#pgname", (v) => (this._page().name = v));
    bindPageProp("#pgparent", (v) => (this._page().parent = v || null));
    bindPageProp("#pgcolor", (v) => (this._page().pageNameColor = v || undefined));

    $$("input[data-f], select[data-f]").forEach((el) =>
      el.addEventListener("change", (e) => {
        const { f, row, side } = e.target.dataset;
        const line = this._line(Number(row));
        const cfg = line[side];
        const value = e.target.value;
        if (f === "label") cfg.label = value;
        else if (f === "btnType") {
          cfg.button.type = value;
          if (value !== "navigation") cfg.button.target = "";
        } else if (f === "btnTarget") cfg.button.target = value;
        else cfg.display[f] = value;
        this._touch();
      })
    );

    $$(".mcdu pre").forEach((pre) =>
      pre.addEventListener("click", () => {
        const row = Number(pre.dataset.row);
        const dataRow = row % 2 === 0 ? row + 1 : row;
        const slot = this.shadowRoot.querySelector(`#slot-${dataRow}`);
        if (slot) {
          $$(".slot").forEach((s) => s.classList.remove("highlight"));
          slot.classList.add("highlight");
          slot.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      })
    );

    const prevpg = $("#prevpg");
    if (prevpg)
      prevpg.addEventListener("click", () => {
        this._previewOffset--;
        this._fetchPreview();
      });
    const nextpg = $("#nextpg");
    if (nextpg)
      nextpg.addEventListener("click", () => {
        this._previewOffset++;
        this._fetchPreview();
      });
  }
}

function escapeHtml(text) {
  return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

customElements.define("mcdu-panel", McduPanel);
