/**
 * MCDU configuration panel (custom sidebar panel).
 *
 * Self-contained web component, no build step.
 *
 * Layout: left column = standard functions (device, page tree, save) with the
 * context editor below; right column = an interactive image of the WinWing
 * MCDU (display, LSKs, function keys, LEDs). Click any element on the MCDU to
 * configure it — LSKs/display rows edit page lines, function keys get page
 * assignments, LEDs get entity bindings. The display preview is rendered by
 * the SAME PageEngine that drives the hardware.
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

// Function key rows as on the hardware (null = blank cap, "BRT"/"DIM" static)
const FK_ROWS = [
  [
    { key: "DIR", label: "DIR" },
    { key: "PROG", label: "PROG" },
    { key: "PERF", label: "PERF" },
    { key: "INIT", label: "INIT" },
    { key: "DATA", label: "DATA" },
    null,
    { key: "BRT", label: "BRT", static: true },
  ],
  [
    { key: "FPLN", label: "F-PLN" },
    { key: "RAD", label: "RAD<br>NAV" },
    { key: "FUEL", label: "FUEL<br>PRED" },
    { key: "SEC", label: "SEC<br>F-PLN" },
    { key: "ATC", label: "ATC<br>COMM" },
    { key: "MENU", label: "MCDU<br>MENU" },
    { key: "DIM", label: "DIM", static: true },
  ],
];
const LEDS_LEFT = ["FAIL", "FM", "MCDU", "MENU"];
const LEDS_RIGHT = ["FM1", "IND", "RDY", "STATUS", "FM2"];

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
    this._functionKeys = {};
    this._ledBindings = {};
    this._selectedPageId = null;
    this._sel = { kind: "page" };
    this._dirty = false;
    this._previewLines = null;
    this._previewOffset = 0;
    this._previewTotal = 1;
    this._previewTimer = null;
    this._initialized = false;
    this._importOpen = false;
    this._dashboards = null;
    this._dashViews = {};
    this._areas = null;
    this._areaEntities = {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._loadDevices();
      // Keep the preview clock current
      this._clockTimer = setInterval(() => this._schedulePreview(), 60000);
    }
  }

  disconnectedCallback() {
    clearInterval(this._clockTimer);
    clearTimeout(this._previewTimer);
  }

  set narrow(_v) {}
  set panel(_v) {}

  // ================= backend =================

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
    this._functionKeys = { ...(result.function_keys || {}) };
    this._ledBindings = { ...(result.led_bindings || {}) };
    this._selectedPageId = result.current_page || (this._pages[0] && this._pages[0].id) || null;
    this._sel = { kind: "page" };
    this._dirty = false;
    this._previewOffset = 0;
    this._schedulePreview();
  }

  async _save() {
    try {
      await this._hass.callWS({
        type: "mcdu/pages/save",
        entry_id: this._entryId,
        pages: this._pages,
        function_keys: this._functionKeys,
        led_bindings: this._ledBindings,
      });
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

  // ================= data =================

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
    for (const side of ["left", "right"]) {
      if (!line[side]) line[side] = EMPTY_SIDE();
      if (!line[side].display) line[side].display = EMPTY_SIDE().display;
      if (!line[side].button) line[side].button = EMPTY_SIDE().button;
    }
    return line;
  }

  _linesWithContent(page) {
    return (page.lines || []).filter((line) =>
      ["left", "right"].some((s) => {
        const cfg = line[s];
        return cfg && ((cfg.display && (cfg.display.source || cfg.display.text)) || cfg.label);
      })
    );
  }

  /** Display slot (0-5) on the current preview screen → line row (creates rows lazily). */
  _rowForSlot(slotIdx) {
    const page = this._page();
    if (!page) return null;
    if (this._previewTotal > 1) {
      const items = this._linesWithContent(page);
      const item = items[this._previewOffset * 6 + slotIdx];
      if (item) return item.row;
      const maxRow = Math.max(1, ...(page.lines || []).map((l) => l.row));
      return maxRow + 2;
    }
    return 3 + 2 * slotIdx;
  }

  _sideType(cfg) {
    if (!cfg) return "none";
    if (cfg.button && cfg.button.type === "navigation") return "page";
    if (cfg.display && cfg.display.source) return "entity";
    if (cfg.display && cfg.display.text) return "text";
    return "none";
  }

  _setSideType(cfg, type) {
    if (type === "none") {
      cfg.label = "";
      cfg.display = EMPTY_SIDE().display;
      cfg.button = EMPTY_SIDE().button;
    } else if (type === "text") {
      cfg.display.source = "";
      cfg.button = EMPTY_SIDE().button;
    } else if (type === "entity") {
      cfg.display.text = "";
      cfg.button = EMPTY_SIDE().button;
    } else if (type === "page") {
      cfg.display.source = "";
      cfg.button = { type: "navigation", target: "" };
    }
  }

  _touch() {
    this._dirty = true;
    this._syncDisplayTypes();
    this._schedulePreview();
    this._render();
  }

  _syncDisplayTypes() {
    for (const page of this._pages) {
      for (const line of page.lines || []) {
        for (const side of ["left", "right"]) {
          const d = line[side] && line[side].display;
          if (!d) continue;
          d.type = d.source ? "datapoint" : d.text ? "label" : "empty";
        }
      }
    }
  }

  _slugify(name) {
    let base =
      name
        .toLowerCase()
        .replace(/[äöüß]/g, (c) => ({ ä: "ae", ö: "oe", ü: "ue", ß: "ss" })[c])
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "page";
    let id = base;
    let n = 1;
    while (this._pages.some((p) => p.id === id)) id = `${base}-${++n}`;
    return id;
  }

  _addPage() {
    const id = this._slugify(`page ${this._pages.length + 1}`);
    this._pages.push({
      id,
      name: `PAGE ${this._pages.length + 1}`,
      parent: this._selectedPageId || null,
      lines: [],
    });
    this._selectedPageId = id;
    this._sel = { kind: "page" };
    this._touch();
  }

  _deletePage() {
    const page = this._page();
    if (!page) return;
    if (!confirm(`Delete page "${page.name || page.id}"?`)) return;
    this._pages = this._pages.filter((p) => p.id !== page.id);
    for (const p of this._pages) if (p.parent === page.id) p.parent = null;
    for (const [key, target] of Object.entries(this._functionKeys)) {
      if (target === page.id) delete this._functionKeys[key];
    }
    this._selectedPageId = this._pages[0] ? this._pages[0].id : null;
    this._sel = { kind: "page" };
    this._touch();
  }

  _createPageFromEntities(name, items) {
    const sideFor = (item) => {
      const st = this._hass.states[item.entity];
      const label = (item.name || (st && st.attributes.friendly_name) || item.entity)
        .toUpperCase()
        .slice(0, 11);
      return {
        label,
        display: {
          type: "datapoint",
          text: "",
          colLabel: "",
          colData: "",
          source: item.entity,
          format: "",
          unit: (st && st.attributes.unit_of_measurement) || "",
        },
        button: { type: "empty", target: "" },
      };
    };
    const lines = [];
    for (let i = 0; i < items.length; i += 2) {
      const line = { row: 3 + i, left: sideFor(items[i]), right: EMPTY_SIDE() };
      if (items[i + 1]) line.right = sideFor(items[i + 1]);
      lines.push(line);
    }
    const id = this._slugify(name);
    this._pages.push({
      id,
      name: name.toUpperCase().slice(0, 14),
      parent: this._selectedPageId || null,
      lines,
    });
    this._selectedPageId = id;
    this._sel = { kind: "page" };
    this._importOpen = false;
    this._touch();
  }

  // ================= import: dashboards & areas =================

  async _openImport() {
    this._importOpen = true;
    this._render();
    if (!this._dashboards) {
      try {
        const list = await this._hass.callWS({ type: "lovelace/dashboards/list" });
        this._dashboards = [{ url_path: null, title: "Default dashboard" }, ...list];
      } catch (err) {
        this._dashboards = [{ url_path: null, title: "Default dashboard" }];
      }
      this._render();
    }
  }

  async _loadDashViews(urlPath) {
    const key = urlPath || "__default__";
    if (this._dashViews[key]) return;
    try {
      const config = await this._hass.callWS({ type: "lovelace/config", url_path: urlPath });
      this._dashViews[key] = (config.views || []).map((view, idx) => ({
        idx,
        title: view.title || view.path || `View ${idx + 1}`,
        entities: this._collectViewEntities(view),
      }));
    } catch (err) {
      this._dashViews[key] = { error: "Could not read this dashboard (YAML mode?)" };
    }
    this._render();
  }

  _collectViewEntities(view) {
    const out = [];
    const seen = new Set();
    const push = (entity, name) => {
      if (!entity || typeof entity !== "string" || seen.has(entity)) return;
      if (!this._hass.states[entity]) return;
      const domain = entity.split(".")[0];
      if (["camera", "update", "person", "zone", "automation", "script", "scene"].includes(domain))
        return;
      seen.add(entity);
      out.push({ entity, name });
    };
    const walkCard = (card) => {
      if (!card || typeof card !== "object") return;
      if (typeof card.entity === "string") push(card.entity, card.name);
      if (Array.isArray(card.entities)) {
        for (const e of card.entities) {
          if (typeof e === "string") push(e);
          else if (e && typeof e.entity === "string") push(e.entity, e.name);
        }
      }
      if (Array.isArray(card.cards)) card.cards.forEach(walkCard);
      if (card.card) walkCard(card.card);
    };
    (view.cards || []).forEach(walkCard);
    (view.sections || []).forEach((sec) => (sec.cards || []).forEach(walkCard));
    return out;
  }

  async _loadAreas() {
    if (this._areas) return;
    const [areas, entities, devices] = await Promise.all([
      this._hass.callWS({ type: "config/area_registry/list" }),
      this._hass.callWS({ type: "config/entity_registry/list" }),
      this._hass.callWS({ type: "config/device_registry/list" }),
    ]);
    const deviceArea = {};
    for (const d of devices) deviceArea[d.id] = d.area_id;
    this._areaEntities = {};
    const GEN = ["light", "switch", "cover", "climate", "media_player", "number", "input_number", "sensor", "binary_sensor"];
    for (const e of entities) {
      if (e.disabled_by || e.hidden_by) continue;
      const area = e.area_id || deviceArea[e.device_id];
      if (!area) continue;
      const domain = e.entity_id.split(".")[0];
      if (!GEN.includes(domain) || !this._hass.states[e.entity_id]) continue;
      if (!this._areaEntities[area]) this._areaEntities[area] = [];
      this._areaEntities[area].push(e.entity_id);
    }
    for (const list of Object.values(this._areaEntities)) {
      list.sort((a, b) => GEN.indexOf(a.split(".")[0]) - GEN.indexOf(b.split(".")[0]));
    }
    this._areas = areas.sort((a, b) => a.name.localeCompare(b.name));
    this._render();
  }

  // ================= rendering =================

  _renderError(message) {
    this.shadowRoot.innerHTML = `<p style="padding:24px;color:var(--error-color,#c62828)">${message}</p>`;
  }

  _entityOptions() {
    if (!this._hass) return "";
    return Object.keys(this._hass.states)
      .sort()
      .map((id) => {
        const name = this._hass.states[id].attributes.friendly_name || "";
        return `<option value="${id}">${escapeHtml(name)}</option>`;
      })
      .join("");
  }

  _style() {
    return `<style>
      :host { display:block; height:100%; overflow:auto;
              background: var(--primary-background-color); color: var(--primary-text-color);
              font-family: var(--paper-font-body1_-_font-family, sans-serif); }
      .layout { display:flex; gap:16px; padding:16px; flex-wrap:wrap; align-items:flex-start; }
      .card { background: var(--card-background-color); border-radius: 12px;
              box-shadow: var(--ha-card-box-shadow, 0 1px 4px rgba(0,0,0,.2)); padding:16px; }
      .leftcol { flex:1; min-width:360px; max-width:560px; display:flex; flex-direction:column; gap:16px; }
      h2 { margin: 0 0 12px; font-size: 18px; }
      h3 { margin: 0 0 10px; font-size: 13px; opacity:.8; text-transform: uppercase; letter-spacing:.5px; }
      select, input { background: var(--secondary-background-color); color: var(--primary-text-color);
              border: 1px solid var(--divider-color); border-radius: 6px; padding: 5px 7px;
              font-size: 13px; box-sizing: border-box; }
      input:focus, select:focus { outline: 2px solid var(--primary-color); }
      .pagelist { list-style:none; margin:8px 0; padding:0; max-height: 30vh; overflow:auto; }
      .pagelist li { padding: 6px 10px; border-radius:6px; cursor:pointer; }
      .pagelist li.sel { background: var(--primary-color); color: var(--text-primary-color,#fff); }
      .pagelist li:hover:not(.sel) { background: var(--secondary-background-color); }
      .btn { background: var(--primary-color); color: var(--text-primary-color,#fff);
             border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }
      .btn[disabled] { opacity:.4; cursor:default; }
      .btn.ghost { background:transparent; color: var(--primary-color); border:1px solid var(--primary-color); }
      .btn.danger { background: var(--error-color,#c62828); }
      .row { display:flex; gap:10px; align-items:flex-end; margin-bottom:10px; flex-wrap:wrap; }
      .toolbar { display:flex; gap:8px; align-items:center; margin-top:10px; }
      .dirty { color: var(--warning-color,#ffa600); font-size:12px; }
      .muted { opacity:.6; font-size:12px; }
      label.small { display:block; font-size:11px; opacity:.7; margin:6px 0 2px; }
      .editor input, .editor select { width:100%; }
      .grid2 { display:grid; grid-template-columns: 1fr 1fr; gap:8px; }
      .typesel { display:flex; gap:4px; margin:6px 0 10px; }
      .typesel button { flex:1; padding:5px 2px; font-size:12px; border-radius:6px; cursor:pointer;
              border:1px solid var(--divider-color); background:var(--secondary-background-color);
              color: var(--primary-text-color); }
      .typesel button.on { background: var(--primary-color); color:var(--text-primary-color,#fff);
              border-color: var(--primary-color); }

      /* ---------- MCDU graphic ---------- */
      .mcduCol { width: 520px; flex-shrink: 0; }
      .mcdu { background: linear-gradient(#5a6472,#49525f); border-radius:16px; padding:14px;
              border: 1px solid #333; user-select:none; }
      .disp-area { display:flex; gap:4px; align-items:stretch; }
      .lskcol { display:grid; grid-template-rows: repeat(14, 1fr); width:34px; }
      .lsk { grid-row: span 1; align-self:center; justify-self:center; width:28px; height:13px;
             background:#1c1c1c; border-radius:3px; border:1px solid #000; cursor:pointer;
             box-shadow: inset 0 0 3px #000; position:relative; }
      .lsk::after { content:""; position:absolute; inset:4px 5px; background:#c9c9c9; border-radius:1px; }
      .lsk:hover { outline:2px solid var(--primary-color); }
      .lsk.sel { outline:2px solid var(--primary-color); }
      .screen { flex:1; background:#0a0a0a; border-radius:8px; border:6px solid #2a2f38;
             padding:10px 6px; display:flex; flex-direction:column; align-items:center;
             justify-content:space-between; }
      .screen pre { margin:0; font-family:"Courier New",monospace; font-size:25px; line-height:1.28;
             letter-spacing:0; cursor:pointer; }
      .screen pre:hover { background:#16202a; }
      .pager { display:flex; gap:8px; justify-content:center; margin:6px 0; align-items:center; }
      .kbd-area { display:flex; gap:6px; margin-top:10px; }
      .ledstrip { width:44px; display:flex; flex-direction:column; gap:6px; align-items:stretch;
             padding-top:6px; }
      .led { background:#2a2f38; border:1px solid #222; border-radius:4px; padding:4px 2px;
             text-align:center; cursor:pointer; }
      .led:hover { outline:2px solid var(--primary-color); }
      .led.sel { outline:2px solid var(--primary-color); }
      .led .dot { display:block; margin:0 auto 2px; width:16px; height:6px; border-radius:2px;
             background:#3a3a3a; }
      .led.bound .dot { background:#ffb400; box-shadow:0 0 6px #ffb400; }
      .led span.name { font-size:8px; color:#ccc; font-family:monospace; letter-spacing:.5px; }
      .keys { flex:1; }
      .fkrow { display:flex; gap:6px; margin-bottom:6px; }
      .fk { flex:1; background:#1c1c1c; color:#e8e8e8; border:1px solid #000; border-radius:5px;
             font-family: Arial, sans-serif; font-size:10px; font-weight:bold; text-align:center;
             padding:6px 2px; cursor:pointer; line-height:1.15; min-height:26px;
             display:flex; align-items:center; justify-content:center; }
      .fk:hover { outline:2px solid var(--primary-color); }
      .fk.sel { outline:2px solid var(--primary-color); }
      .fk.assigned { color:#7fd58a; box-shadow: inset 0 0 6px rgba(80,220,110,.35); }
      .fk.blank { background:#242424; cursor:default; }
      .fk.static { background:#111; color:#999; cursor:default; }
      .fk.static:hover { outline:none; }
      .keypad { display:flex; gap:8px; margin-top:4px; }
      .numpad { display:grid; grid-template-columns:repeat(3, 24px); gap:5px; align-content:start; }
      .num { width:24px; height:24px; border-radius:50%; background:#1c1c1c; color:#eee;
             font-size:10px; display:flex; align-items:center; justify-content:center;
             font-family:monospace; border:1px solid #000; }
      .alpha { flex:1; display:grid; grid-template-columns:repeat(5, 1fr); gap:5px; }
      .key { height:24px; border-radius:4px; background:#1c1c1c; color:#eee; font-size:10px;
             display:flex; align-items:center; justify-content:center; font-family:monospace;
             border:1px solid #000; }
      .slew { display:grid; grid-template-columns:repeat(2, 30px); gap:5px; margin:4px 0 8px; }
      .slewkey { height:20px; border-radius:4px; background:#1c1c1c; color:#eee; font-size:11px;
             display:flex; align-items:center; justify-content:center; border:1px solid #000; }

      .overlay { position:fixed; inset:0; background:rgba(0,0,0,.5); display:flex;
             align-items:center; justify-content:center; z-index:10; }
      .dialog { background: var(--card-background-color); border-radius:12px; padding:20px;
             max-width:460px; width:92%; max-height:75vh; overflow:auto; }
      .implist { list-style:none; margin:8px 0; padding:0; }
      .implist li { padding:8px 12px; border-radius:8px; cursor:pointer; display:flex;
             justify-content:space-between; }
      .implist li:hover { background: var(--secondary-background-color); }
      .implist li.head { font-weight:bold; cursor:pointer; }
      .implist li.sub { padding-left:26px; }
    </style>`;
  }

  _render() {
    if (!this._devices.length) {
      this.shadowRoot.innerHTML = `${this._style()}<div class="layout"><div class="card">
        <h2>MCDU</h2><p>No MCDU devices configured yet. Add one via Settings → Devices &amp; Services.</p>
      </div></div>`;
      return;
    }

    this.shadowRoot.innerHTML = `${this._style()}
      <datalist id="entities">${this._entityOptions()}</datalist>
      <div class="layout">
        <div class="leftcol">
          <div class="card">
            <h2>MCDU</h2>
            <div class="row">
              <select id="device" style="flex:1">
                ${this._devices
                  .map(
                    (d) =>
                      `<option value="${d.entry_id}" ${d.entry_id === this._entryId ? "selected" : ""}>
                         ${d.device_id} ${d.online ? "🟢" : "⚪"}</option>`
                  )
                  .join("")}
              </select>
              <button class="btn" id="save" ${this._dirty ? "" : "disabled"}>Save &amp; apply</button>
              ${this._dirty ? '<span class="dirty">●</span>' : ""}
            </div>
            <h3>Pages</h3>
            <ul class="pagelist">${this._renderPageTree()}</ul>
            <div class="row">
              <button class="btn ghost" id="addpage">+ Page</button>
              <button class="btn ghost" id="import">+ Import…</button>
              <button class="btn danger" id="delpage" ${this._page() ? "" : "disabled"}>Delete</button>
            </div>
          </div>
          <div class="card editor">${this._renderContextEditor()}</div>
        </div>

        <div class="card mcduCol">
          <h3>WinWing MCDU — click any element to configure it</h3>
          ${this._renderMcdu()}
        </div>
      </div>
      ${this._importOpen ? this._renderImportDialog() : ""}`;

    this._bindEvents();
  }

  _renderPageTree() {
    const roots = this._pages.filter((p) => !p.parent || !this._pages.some((q) => q.id === p.parent));
    const children = (id) => this._pages.filter((p) => p.parent === id);
    const item = (p, depth) => {
      const sel = p.id === this._selectedPageId ? "sel" : "";
      const pad = 10 + depth * 14;
      let html = `<li class="${sel}" data-page="${p.id}" style="padding-left:${pad}px">
        ${depth ? "└ " : ""}${escapeHtml((p.name || p.id).toUpperCase())}</li>`;
      for (const c of children(p.id)) html += item(c, depth + 1);
      return html;
    };
    return roots.map((p) => item(p, 0)).join("");
  }

  // ---------- MCDU graphic ----------

  _renderMcdu() {
    const lsk = (side) =>
      `<div class="lskcol">${[3, 5, 7, 9, 11, 13]
        .map((row, i) => {
          const sel =
            this._sel.kind === "line" &&
            this._sel.slot === i &&
            this._sel.side === side
              ? "sel"
              : "";
          return `<div class="lsk ${sel}" style="grid-row:${row}" data-lsk="${i}" data-side="${side}"
                     title="LSK${i + 1}${side === "left" ? "L" : "R"}"></div>`;
        })
        .join("")}</div>`;

    const screen = `<div class="screen">${this._renderPreviewLines()}</div>`;

    const fkeys = FK_ROWS.map(
      (row) =>
        `<div class="fkrow">${row
          .map((k) => {
            if (!k) return `<div class="fk blank"></div>`;
            if (k.static)
              return `<div class="fk static" title="${k.key}: fixed function (brightness)">${k.label}</div>`;
            const assigned = this._functionKeys[k.key];
            const sel = this._sel.kind === "fk" && this._sel.key === k.key ? "sel" : "";
            const title = assigned
              ? `${k.key} → ${escapeAttr(this._pageName(assigned))}`
              : `${k.key}: not assigned`;
            return `<div class="fk ${assigned ? "assigned" : ""} ${sel}" data-fk="${k.key}"
                        title="${title}">${k.label}</div>`;
          })
          .join("")}</div>`
    ).join("");

    const ledStrip = (leds) =>
      `<div class="ledstrip">${leds
        .map((name) => {
          const bound = this._ledBindings[name];
          const sel = this._sel.kind === "led" && this._sel.name === name ? "sel" : "";
          const title = bound ? `${name} ← ${escapeAttr(bound)}` : `${name}: not bound`;
          return `<div class="led ${bound ? "bound" : ""} ${sel}" data-led="${name}" title="${title}">
            <span class="dot"></span><span class="name">${name}</span></div>`;
        })
        .join("")}</div>`;

    const airportRow = `<div class="fkrow">
        <div class="fk ${this._functionKeys["AIRPORT"] ? "assigned" : ""} ${
          this._sel.kind === "fk" && this._sel.key === "AIRPORT" ? "sel" : ""
        }" data-fk="AIRPORT" style="max-width:60px"
           title="${this._functionKeys["AIRPORT"] ? `AIRPORT → ${escapeAttr(this._pageName(this._functionKeys["AIRPORT"]))}` : "AIRPORT: not assigned"}">AIR<br>PORT</div>
        <div class="fk blank" style="max-width:60px"></div>
        <div style="flex:1"></div>
      </div>
      <div class="slew">
        <div class="slewkey" title="SLEW: previous sibling page">◄</div>
        <div class="slewkey" title="SLEW: scroll up">▲</div>
        <div class="slewkey" title="SLEW: next sibling page">►</div>
        <div class="slewkey" title="SLEW: scroll down">▼</div>
      </div>`;

    const numpad = `<div class="numpad">${["1","2","3","4","5","6","7","8","9",".","0","±"]
      .map((n) => `<div class="num">${n}</div>`)
      .join("")}</div>`;
    const alpha = `<div class="alpha">${"ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")
      .map((c) => `<div class="key">${c}</div>`)
      .join("")}<div class="key">/</div><div class="key">SP</div><div class="key">OVFY</div><div class="key">CLR</div></div>`;

    return `<div class="mcdu">
      <div class="disp-area">${lsk("left")}${screen}${lsk("right")}</div>
      ${
        this._previewTotal > 1
          ? `<div class="pager">
               <button class="btn ghost" id="prevpg" ${this._previewOffset === 0 ? "disabled" : ""}>▲</button>
               <span class="muted" style="color:#ccc">${this._previewOffset + 1}/${this._previewTotal}</span>
               <button class="btn ghost" id="nextpg" ${
                 this._previewOffset >= this._previewTotal - 1 ? "disabled" : ""
               }>▼</button>
             </div>`
          : ""
      }
      <div class="kbd-area">
        ${ledStrip(LEDS_LEFT)}
        <div class="keys">
          ${fkeys}
          ${airportRow}
          <div class="keypad">${numpad}${alpha}</div>
        </div>
        ${ledStrip(LEDS_RIGHT)}
      </div>
    </div>`;
  }

  _renderPreviewLines() {
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

  _pageName(pageId) {
    const page = this._pages.find((p) => p.id === pageId);
    return page ? page.name || page.id : pageId;
  }

  _pageOptions(selected, excludeId) {
    return (
      `<option value="">—</option>` +
      this._pages
        .filter((p) => p.id !== excludeId)
        .map(
          (p) =>
            `<option value="${p.id}" ${p.id === selected ? "selected" : ""}>${escapeHtml(p.name || p.id)}</option>`
        )
        .join("")
    );
  }

  // ---------- context editor ----------

  _renderContextEditor() {
    const page = this._page();
    if (!page) return "<p>Select or create a page.</p>";

    if (this._sel.kind === "fk") return this._renderFkEditor(this._sel.key);
    if (this._sel.kind === "led") return this._renderLedEditor(this._sel.name);
    if (this._sel.kind === "line") return this._renderLineEditor(page);
    return this._renderPageEditor(page);
  }

  _renderPageEditor(page) {
    const colorOptions = (selected) =>
      `<option value="">default</option>` +
      COLORS.map((c) => `<option ${c === selected ? "selected" : ""}>${c}</option>`).join("");
    return `
      <h3>Page settings</h3>
      <div class="grid2">
        <div><label class="small">Name</label>
          <input id="pgname" value="${escapeAttr(page.name)}" maxlength="24"></div>
        <div><label class="small">Parent page</label>
          <select id="pgparent">${this._pageOptions(page.parent, page.id)}</select></div>
        <div><label class="small">Status bar color</label>
          <select id="pgcolor">${colorOptions(page.pageNameColor)}</select></div>
        <div style="align-self:end" class="muted">id: ${page.id}</div>
      </div>
      <p class="muted" style="margin-top:14px">
        Click an <b>LSK</b> or a <b>display row</b> on the MCDU to edit that line —
        left half edits the left side, right half the right side.<br>
        Click a <b>function key</b> to assign a page, an <b>LED</b> to bind an entity.
      </p>`;
  }

  _renderLineEditor(page) {
    const { row, side, slot } = this._sel;
    const line = this._line(row);
    if (!line) return "<p>—</p>";
    const cfg = line[side];
    const d = cfg.display || {};
    const b = cfg.button || {};
    // The chosen type sticks even while its fields are still empty —
    // otherwise "Text"/"Entity" would collapse back to "—" immediately.
    const type = this._sel.typeOverride || this._sideType(cfg);
    const colorOptions = (selected) =>
      `<option value="">default</option>` +
      COLORS.map((c) => `<option ${c === selected ? "selected" : ""}>${c}</option>`).join("");
    const typeButton = (t, label) =>
      `<button class="${type === t ? "on" : ""}" data-type="${t}">${label}</button>`;

    let fields = "";
    if (type === "text") {
      fields = `
        <label class="small">Text</label>
        <input data-f="text" value="${escapeAttr(d.text)}" maxlength="24">
        <div class="grid2">
          <div><label class="small">Caption (small line above)</label>
            <input data-f="label" value="${escapeAttr(cfg.label)}" maxlength="12"></div>
          <div><label class="small">Color</label>
            <select data-f="colData">${colorOptions(d.colData)}</select></div>
        </div>`;
    } else if (type === "entity") {
      fields = `
        <label class="small">Entity — value shows live, LSK writes/toggles it</label>
        <input data-f="source" value="${escapeAttr(d.source)}" list="entities" placeholder="light.wohnzimmer …">
        <label class="small">Caption (small line above)</label>
        <input data-f="label" value="${escapeAttr(cfg.label)}" maxlength="12">
        <div class="grid2">
          <div><label class="small">Format (e.g. %.1f)</label>
            <input data-f="format" value="${escapeAttr(d.format)}"></div>
          <div><label class="small">Unit</label>
            <input data-f="unit" value="${escapeAttr(d.unit)}"></div>
          <div><label class="small">Caption color</label>
            <select data-f="colLabel">${colorOptions(d.colLabel)}</select></div>
          <div><label class="small">Value color</label>
            <select data-f="colData">${colorOptions(d.colData)}</select></div>
        </div>`;
    } else if (type === "page") {
      fields = `
        <label class="small">Target page — LSK navigates there</label>
        <select data-f="btnTarget">${this._pageOptions(b.target, page.id)}</select>
        <label class="small">Shown text</label>
        <input data-f="text" value="${escapeAttr(d.text)}" maxlength="24"
               placeholder="${side === "left" ? "<LIGHTS" : "LIGHTS>"}">
        <div class="grid2">
          <div><label class="small">Caption (small line above)</label>
            <input data-f="label" value="${escapeAttr(cfg.label)}" maxlength="12"></div>
          <div><label class="small">Color</label>
            <select data-f="colData">${colorOptions(d.colData)}</select></div>
        </div>`;
    } else {
      fields = `<p class="muted">This field is empty — choose what it should be.</p>`;
    }

    const screenInfo = this._previewTotal > 1 ? ` · screen ${this._previewOffset + 1}` : "";
    return `
      <h3>LSK${slot + 1} ${side}${screenInfo}
        <button class="btn ghost" id="backpage" style="float:right;padding:2px 10px;font-size:11px">Page settings</button>
      </h3>
      <div class="typesel">
        ${typeButton("none", "—")}
        ${typeButton("text", "Text")}
        ${typeButton("entity", "Entity")}
        ${typeButton("page", "Page link")}
      </div>
      ${fields}`;
  }

  _renderFkEditor(key) {
    const target = this._functionKeys[key] || "";
    return `
      <h3>Function key ${key}
        <button class="btn ghost" id="backpage" style="float:right;padding:2px 10px;font-size:11px">Page settings</button>
      </h3>
      <label class="small">Pressing ${key} on the hardware jumps to this page (from anywhere):</label>
      <select id="fktarget">${this._pageOptions(target, null)}</select>
      <p class="muted">Choose “—” to unassign the key.</p>`;
  }

  _renderLedEditor(name) {
    const bound = this._ledBindings[name] || "";
    return `
      <h3>LED ${name}
        <button class="btn ghost" id="backpage" style="float:right;padding:2px 10px;font-size:11px">Page settings</button>
      </h3>
      <label class="small">The LED follows this entity — lit while it is on / &gt; 0:</label>
      <input id="ledentity" value="${escapeAttr(bound)}" list="entities" placeholder="binary_sensor.washer_running …">
      <p class="muted">Clear the field to unbind the LED. The two backlights are controlled
      by BRT/DIM and the brightness sliders, not bound here.</p>`;
  }

  _renderImportDialog() {
    let dashHtml = `<li class="muted">loading…</li>`;
    if (this._dashboards) {
      dashHtml = this._dashboards
        .map((d) => {
          const key = d.url_path || "__default__";
          const views = this._dashViews[key];
          let sub = "";
          if (views) {
            sub = views.error
              ? `<li class="sub muted">${views.error}</li>`
              : views
                  .map(
                    (v) =>
                      `<li class="sub" data-dash="${key}" data-view="${v.idx}">
                         <span>${escapeHtml(v.title)}</span>
                         <span class="muted">${v.entities.length} entities</span></li>`
                  )
                  .join("");
          }
          return `<li class="head" data-dashload="${key}" data-path="${d.url_path || ""}">
                    <span>▸ ${escapeHtml(d.title)}</span></li>${sub}`;
        })
        .join("");
    }

    let areaHtml = "";
    if (this._areas) {
      areaHtml = this._areas
        .map((a) => {
          const count = (this._areaEntities[a.area_id] || []).length;
          if (!count) return "";
          return `<li class="sub" data-area="${a.area_id}"><span>${escapeHtml(a.name)}</span>
            <span class="muted">${count} entities</span></li>`;
        })
        .join("");
    } else {
      areaHtml = `<li class="sub" id="loadareas" style="cursor:pointer"><span class="muted">Show areas…</span></li>`;
    }

    return `<div class="overlay" id="overlay">
      <div class="dialog">
        <h3>Import a page</h3>
        <p class="muted">Recommended: import a <b>dashboard view</b> — its entities and names
        are already curated. The new page becomes a child of the current page.</p>
        <ul class="implist">${dashHtml}</ul>
        <h3 style="margin-top:14px">From area (all entities of a room)</h3>
        <ul class="implist">${areaHtml}</ul>
        <div class="toolbar"><button class="btn ghost" id="closedialog">Cancel</button></div>
      </div>
    </div>`;
  }

  // ================= events =================

  _bindEvents() {
    const $ = (sel) => this.shadowRoot.querySelector(sel);
    const $$ = (sel) => this.shadowRoot.querySelectorAll(sel);
    const on = (sel, event, handler) => {
      const el = $(sel);
      if (el) el.addEventListener(event, handler);
    };

    on("#device", "change", async (e) => {
      this._entryId = e.target.value;
      await this._loadPages();
      this._render();
    });
    on("#save", "click", () => this._save());
    on("#addpage", "click", () => this._addPage());
    on("#delpage", "click", () => this._deletePage());
    on("#import", "click", () => this._openImport());
    on("#closedialog", "click", () => {
      this._importOpen = false;
      this._render();
    });
    on("#overlay", "click", (e) => {
      if (e.target.id === "overlay") {
        this._importOpen = false;
        this._render();
      }
    });
    on("#backpage", "click", () => {
      this._sel = { kind: "page" };
      this._render();
    });

    $$(".pagelist li").forEach((li) =>
      li.addEventListener("click", () => {
        this._selectedPageId = li.dataset.page;
        this._sel = { kind: "page" };
        this._previewOffset = 0;
        this._schedulePreview();
        this._render();
      })
    );

    // -- page settings
    const bindPageProp = (id, apply) => {
      on(id, "change", (e) => {
        apply(e.target.value);
        this._touch();
      });
    };
    bindPageProp("#pgname", (v) => (this._page().name = v));
    bindPageProp("#pgparent", (v) => (this._page().parent = v || null));
    bindPageProp("#pgcolor", (v) => (this._page().pageNameColor = v || undefined));

    // -- MCDU graphic clicks
    $$(".lsk").forEach((el) =>
      el.addEventListener("click", () => {
        const slot = Number(el.dataset.lsk);
        const row = this._rowForSlot(slot);
        if (row === null) return;
        this._line(row);
        this._sel = { kind: "line", row, side: el.dataset.side, slot };
        this._render();
      })
    );

    $$(".screen pre").forEach((pre) =>
      pre.addEventListener("click", (e) => {
        const displayRow = Number(pre.dataset.row);
        const dataRow = displayRow % 2 === 0 ? displayRow + 1 : displayRow;
        if (dataRow < 3 || dataRow > 13) return;
        const slot = (dataRow - 3) / 2;
        const row = this._rowForSlot(slot);
        if (row === null) return;
        const rect = pre.getBoundingClientRect();
        const side = e.clientX - rect.left < rect.width / 2 ? "left" : "right";
        this._line(row);
        this._sel = { kind: "line", row, side, slot };
        this._render();
      })
    );

    $$(".fk[data-fk]").forEach((el) =>
      el.addEventListener("click", () => {
        this._sel = { kind: "fk", key: el.dataset.fk };
        this._render();
      })
    );

    $$(".led").forEach((el) =>
      el.addEventListener("click", () => {
        this._sel = { kind: "led", name: el.dataset.led };
        this._render();
      })
    );

    // -- line editor
    $$(".typesel button").forEach((btn) =>
      btn.addEventListener("click", () => {
        const line = this._line(this._sel.row);
        this._setSideType(line[this._sel.side], btn.dataset.type);
        this._sel.typeOverride = btn.dataset.type === "none" ? null : btn.dataset.type;
        this._touch();
      })
    );

    $$("input[data-f], select[data-f]").forEach((el) =>
      el.addEventListener("change", (e) => {
        const line = this._line(this._sel.row);
        const cfg = line[this._sel.side];
        const f = e.target.dataset.f;
        const value = e.target.value;
        if (f === "label") cfg.label = value;
        else if (f === "btnTarget") cfg.button.target = value;
        else cfg.display[f] = value;
        this._touch();
      })
    );

    // -- fk editor
    on("#fktarget", "change", (e) => {
      const key = this._sel.key;
      if (e.target.value) this._functionKeys[key] = e.target.value;
      else delete this._functionKeys[key];
      this._dirty = true;
      this._render();
    });

    // -- led editor
    on("#ledentity", "change", (e) => {
      const name = this._sel.name;
      if (e.target.value) this._ledBindings[name] = e.target.value;
      else delete this._ledBindings[name];
      this._dirty = true;
      this._render();
    });

    // -- import dialog
    $$("li[data-dashload]").forEach((li) =>
      li.addEventListener("click", () => this._loadDashViews(li.dataset.path || null))
    );
    $$("li[data-view]").forEach((li) =>
      li.addEventListener("click", () => {
        const views = this._dashViews[li.dataset.dash];
        const view = views && views[Number(li.dataset.view)];
        if (!view || !view.entities.length) {
          alert("This view contains no usable entities.");
          return;
        }
        this._createPageFromEntities(view.title, view.entities);
      })
    );
    on("#loadareas", "click", () => this._loadAreas());
    $$("li[data-area]").forEach((li) =>
      li.addEventListener("click", () => {
        const area = this._areas.find((a) => a.area_id === li.dataset.area);
        const ids = (this._areaEntities[li.dataset.area] || []).slice(0, 36);
        if (!area || !ids.length) return;
        this._createPageFromEntities(area.name, ids.map((entity) => ({ entity })));
      })
    );

    // -- preview pagination
    on("#prevpg", "click", () => {
      this._previewOffset--;
      this._fetchPreview();
    });
    on("#nextpg", "click", () => {
      this._previewOffset++;
      this._fetchPreview();
    });
  }
}

function escapeHtml(text) {
  return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;");
}

customElements.define("mcdu-panel", McduPanel);
