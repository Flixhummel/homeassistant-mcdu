/**
 * MCDU configuration panel (custom sidebar panel).
 *
 * Self-contained web component, no build step. Talks to the integration via
 * the HA WebSocket API (mcdu/devices, mcdu/pages/get, mcdu/pages/save,
 * mcdu/preview). The preview is rendered by the SAME PageEngine that drives
 * the hardware, so what you see is what the display shows.
 *
 * UX model: each line side is ONE of — nothing, static text, an entity
 * (live value, LSK writes/toggles it), or a page link. Only the fields
 * relevant for the chosen type are shown.
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
const FK_LAYOUT = [
  ["DIR", "PROG", "PERF", "INIT", "DATA"],
  ["FPLN", "RAD", "FUEL", "SEC", "ATC"],
  ["MENU", "AIRPORT"],
];
const GEN_DOMAINS = [
  "light",
  "switch",
  "cover",
  "climate",
  "media_player",
  "number",
  "input_number",
  "sensor",
  "binary_sensor",
];

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
    this._selectedPageId = null;
    this._dirty = false;
    this._previewLines = null;
    this._previewOffset = 0;
    this._previewTotal = 1;
    this._previewTimer = null;
    this._initialized = false;
    this._areaDialogOpen = false;
    this._areas = null;
    this._areaEntities = {};
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

  // ---- backend ------------------------------------------------------

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
    this._selectedPageId = result.current_page || (this._pages[0] && this._pages[0].id) || null;
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
    for (const side of ["left", "right"]) {
      if (!line[side]) line[side] = EMPTY_SIDE();
      if (!line[side].display) line[side].display = EMPTY_SIDE().display;
      if (!line[side].button) line[side].button = EMPTY_SIDE().button;
    }
    return line;
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
    this._pages.push({ id, name: `PAGE ${this._pages.length + 1}`, parent: this._selectedPageId || null, lines: [] });
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
    for (const [key, target] of Object.entries(this._functionKeys)) {
      if (target === page.id) delete this._functionKeys[key];
    }
    this._selectedPageId = this._pages[0] ? this._pages[0].id : null;
    this._touch();
  }

  // ---- area generator -----------------------------------------------

  async _openAreaDialog() {
    if (!this._areas) {
      const [areas, entities, devices] = await Promise.all([
        this._hass.callWS({ type: "config/area_registry/list" }),
        this._hass.callWS({ type: "config/entity_registry/list" }),
        this._hass.callWS({ type: "config/device_registry/list" }),
      ]);
      const deviceArea = {};
      for (const d of devices) deviceArea[d.id] = d.area_id;
      this._areaEntities = {};
      for (const e of entities) {
        if (e.disabled_by || e.hidden_by) continue;
        const area = e.area_id || deviceArea[e.device_id];
        if (!area) continue;
        if (!this._areaEntities[area]) this._areaEntities[area] = [];
        this._areaEntities[area].push(e.entity_id);
      }
      this._areas = areas.sort((a, b) => a.name.localeCompare(b.name));
    }
    this._areaDialogOpen = true;
    this._render();
  }

  _generateFromArea(area) {
    const ids = (this._areaEntities[area.area_id] || [])
      .filter((id) => GEN_DOMAINS.includes(id.split(".")[0]))
      .filter((id) => this._hass.states[id])
      .sort(
        (a, b) =>
          GEN_DOMAINS.indexOf(a.split(".")[0]) - GEN_DOMAINS.indexOf(b.split(".")[0])
      )
      .slice(0, 36);

    if (!ids.length) {
      alert(`No supported entities found in "${area.name}".`);
      return;
    }

    const sideFor = (id) => {
      const st = this._hass.states[id];
      const name = (st.attributes.friendly_name || id).toUpperCase().slice(0, 11);
      return {
        label: name,
        display: {
          type: "datapoint",
          text: "",
          colLabel: "",
          colData: "",
          source: id,
          format: "",
          unit: st.attributes.unit_of_measurement || "",
        },
        button: { type: "empty", target: "" },
      };
    };

    const lines = [];
    for (let i = 0; i < ids.length; i += 2) {
      const line = { row: 3 + i, left: sideFor(ids[i]), right: EMPTY_SIDE() };
      if (ids[i + 1]) line.right = sideFor(ids[i + 1]);
      lines.push(line);
    }

    const id = this._slugify(area.name);
    this._pages.push({
      id,
      name: area.name.toUpperCase().slice(0, 14),
      parent: this._selectedPageId || null,
      lines,
    });
    this._selectedPageId = id;
    this._areaDialogOpen = false;
    this._touch();
  }

  // ---- rendering ----------------------------------------------------

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
        .main { flex:1; min-width:480px; display:flex; flex-direction:column; gap:16px; }
        .previewbox { width: 460px; flex-shrink:0; position: sticky; top: 16px; }
        h2 { margin: 4px 0 12px; font-size: 18px; }
        h3 { margin: 0 0 10px; font-size: 13px; opacity:.8; text-transform: uppercase; letter-spacing:.5px; }
        select, input { background: var(--secondary-background-color); color: var(--primary-text-color);
                border: 1px solid var(--divider-color); border-radius: 6px; padding: 5px 7px;
                font-size: 13px; box-sizing: border-box; }
        input:focus, select:focus { outline: 2px solid var(--primary-color); }
        .pagelist { list-style:none; margin:8px 0; padding:0; max-height: 40vh; overflow:auto; }
        .pagelist li { padding: 6px 10px; border-radius:6px; cursor:pointer; }
        .pagelist li.sel { background: var(--primary-color); color: var(--text-primary-color,#fff); }
        .pagelist li:hover:not(.sel) { background: var(--secondary-background-color); }
        .btn { background: var(--primary-color); color: var(--text-primary-color,#fff);
               border:none; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }
        .btn[disabled] { opacity:.4; cursor:default; }
        .btn.ghost { background:transparent; color: var(--primary-color); border:1px solid var(--primary-color); }
        .btn.danger { background: var(--error-color,#c62828); }
        .row { display:flex; gap:10px; align-items:flex-end; margin-bottom:10px; flex-wrap:wrap; }
        .slot { border:1px solid var(--divider-color); border-radius:10px; padding:10px 12px; margin-bottom:10px; }
        .slot.highlight { outline: 2px solid var(--primary-color); }
        .slot h4 { margin:0 0 8px; font-size:12px; opacity:.7; }
        .sides { display:grid; grid-template-columns: 1fr 1fr; gap:14px; }
        .side label { display:block; font-size:11px; opacity:.7; margin:6px 0 2px; }
        .side input, .side select { width:100%; }
        .typesel { display:flex; gap:4px; margin-bottom:4px; }
        .typesel button { flex:1; padding:4px 2px; font-size:11px; border-radius:6px; cursor:pointer;
                border:1px solid var(--divider-color); background:var(--secondary-background-color);
                color: var(--primary-text-color); }
        .typesel button.on { background: var(--primary-color); color:var(--text-primary-color,#fff);
                border-color: var(--primary-color); }
        .grid2 { display:grid; grid-template-columns: 1fr 1fr; gap:6px; }
        .mcdu { background:#0a0a0a; border-radius:12px; padding:18px 14px; border: 3px solid #333; }
        .mcdu pre { margin:0; font-family:"Courier New",monospace; font-size:15px; line-height:1.5;
                    letter-spacing:1px; cursor:pointer; }
        .toolbar { display:flex; gap:8px; align-items:center; margin-top:10px; }
        .dirty { color: var(--warning-color,#ffa600); font-size:12px; }
        .pager { display:flex; gap:8px; justify-content:center; margin-top:8px; align-items:center; }
        .muted { opacity:.6; font-size:12px; }
        .fkgrid { display:flex; flex-direction:column; gap:8px; }
        .fkrow { display:flex; gap:8px; }
        .fk { flex:1; min-width:0; background:#1b1b1b; border:1px solid #444; border-radius:8px;
              padding:6px; text-align:center; }
        .fk.assigned { border-color: var(--primary-color); }
        .fk .keyname { color:#ddd; font-family:"Courier New",monospace; font-size:12px;
              font-weight:bold; letter-spacing:1px; display:block; margin-bottom:4px; }
        .fk select { width:100%; font-size:11px; padding:3px; }
        .overlay { position:fixed; inset:0; background:rgba(0,0,0,.5); display:flex;
              align-items:center; justify-content:center; z-index:10; }
        .dialog { background: var(--card-background-color); border-radius:12px; padding:20px;
              max-width:420px; width:90%; max-height:70vh; overflow:auto; }
        .arealist { list-style:none; margin:10px 0 0; padding:0; }
        .arealist li { padding:9px 12px; border-radius:8px; cursor:pointer; display:flex;
              justify-content:space-between; }
        .arealist li:hover { background: var(--secondary-background-color); }
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
          <h3 style="margin-top:16px">Pages</h3>
          <ul class="pagelist">${this._renderPageTree()}</ul>
          <div class="row">
            <button class="btn ghost" id="addpage">+ Page</button>
            <button class="btn ghost" id="addarea">+ From area</button>
          </div>
          <div class="row">
            <button class="btn danger" id="delpage" ${page ? "" : "disabled"}>Delete page</button>
          </div>
          <div class="toolbar">
            <button class="btn" id="save" ${this._dirty ? "" : "disabled"}>Save &amp; apply</button>
            ${this._dirty ? '<span class="dirty">● unsaved</span>' : ""}
          </div>
        </div>

        <div class="main">
          <div class="card">${page ? this._renderEditor(page) : "<p>Select or create a page.</p>"}</div>
          <div class="card">
            <h3>Function keys</h3>
            <p class="muted" style="margin-top:-6px">Assign a page to a hardware key — pressing it jumps there from anywhere.</p>
            <div class="fkgrid">${this._renderFunctionKeys()}</div>
          </div>
        </div>

        <div class="card previewbox">
          <h3>Live preview</h3>
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
      </div>
      ${this._areaDialogOpen ? this._renderAreaDialog() : ""}`;

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

  _renderFunctionKeys() {
    return FK_LAYOUT.map(
      (row) =>
        `<div class="fkrow">${row
          .map((key) => {
            const target = this._functionKeys[key] || "";
            return `<div class="fk ${target ? "assigned" : ""}">
              <span class="keyname">${key}</span>
              <select data-fk="${key}">${this._pageOptions(target, null)}</select>
            </div>`;
          })
          .join("")}</div>`
    ).join("");
  }

  _renderEditor(page) {
    const colorOptions = (selected) =>
      `<option value="">default</option>` +
      COLORS.map((c) => `<option ${c === selected ? "selected" : ""}>${c}</option>`).join("");

    const slotHtml = this._editorRows(page).map((row, i) => {
      const line = page.lines ? page.lines.find((l) => l.row === row) : null;
      const sideHtml = (s) => {
        const cfg = (line && line[s]) || EMPTY_SIDE();
        const d = cfg.display || {};
        const b = cfg.button || {};
        const type = this._sideType(cfg);
        const typeButton = (t, label) =>
          `<button class="${type === t ? "on" : ""}" data-type="${t}" data-row="${row}" data-side="${s}">${label}</button>`;

        let fields = "";
        if (type === "text") {
          fields = `
            <label>Text</label>
            <input data-f="text" data-row="${row}" data-side="${s}" value="${escapeAttr(d.text)}" maxlength="24">
            <div class="grid2">
              <div><label>Caption (small line above)</label>
                <input data-f="label" data-row="${row}" data-side="${s}" value="${escapeAttr(cfg.label)}" maxlength="12"></div>
              <div><label>Color</label>
                <select data-f="colData" data-row="${row}" data-side="${s}">${colorOptions(d.colData)}</select></div>
            </div>`;
        } else if (type === "entity") {
          fields = `
            <label>Entity — value shows live, LSK writes/toggles it</label>
            <input data-f="source" data-row="${row}" data-side="${s}" value="${escapeAttr(d.source)}" list="entities" placeholder="light.wohnzimmer …">
            <label>Caption (small line above)</label>
            <input data-f="label" data-row="${row}" data-side="${s}" value="${escapeAttr(cfg.label)}" maxlength="12">
            <div class="grid2">
              <div><label>Format (e.g. %.1f)</label>
                <input data-f="format" data-row="${row}" data-side="${s}" value="${escapeAttr(d.format)}"></div>
              <div><label>Unit</label>
                <input data-f="unit" data-row="${row}" data-side="${s}" value="${escapeAttr(d.unit)}"></div>
              <div><label>Caption color</label>
                <select data-f="colLabel" data-row="${row}" data-side="${s}">${colorOptions(d.colLabel)}</select></div>
              <div><label>Value color</label>
                <select data-f="colData" data-row="${row}" data-side="${s}">${colorOptions(d.colData)}</select></div>
            </div>`;
        } else if (type === "page") {
          fields = `
            <label>Target page — LSK navigates there</label>
            <select data-f="btnTarget" data-row="${row}" data-side="${s}">${this._pageOptions(b.target, page.id)}</select>
            <label>Shown text</label>
            <input data-f="text" data-row="${row}" data-side="${s}" value="${escapeAttr(d.text)}" maxlength="24"
                   placeholder="${s === "left" ? "<LIGHTS" : "LIGHTS>"}">
            <div class="grid2">
              <div><label>Caption (small line above)</label>
                <input data-f="label" data-row="${row}" data-side="${s}" value="${escapeAttr(cfg.label)}" maxlength="12"></div>
              <div><label>Color</label>
                <select data-f="colData" data-row="${row}" data-side="${s}">${colorOptions(d.colData)}</select></div>
            </div>`;
        }

        return `<div class="side">
          <div class="typesel">
            ${typeButton("none", "—")}
            ${typeButton("text", "Text")}
            ${typeButton("entity", "Entity")}
            ${typeButton("page", "Page link")}
          </div>
          ${fields}
        </div>`;
      };
      const lsk = (i % 6) + 1;
      const screen = Math.floor(i / 6) + 1;
      const title =
        this._editorRows(page).length > 6
          ? `LSK${lsk} — screen ${screen}`
          : `LSK${lsk} left / right`;
      return `<div class="slot" id="slot-${row}">
        <h4>${title}
          <button class="btn ghost delline" data-row="${row}"
                  style="float:right;padding:1px 8px;font-size:11px">✕</button></h4>
        <div class="sides">${sideHtml("left")}${sideHtml("right")}</div>
      </div>`;
    }).join("");

    return `
      <div class="row">
        <div><label class="muted">Name</label><br>
          <input id="pgname" value="${escapeAttr(page.name)}" maxlength="24"></div>
        <div><label class="muted">Parent page</label><br>
          <select id="pgparent">${this._pageOptions(page.parent, page.id)}</select></div>
        <div><label class="muted">Status bar color</label><br>
          <select id="pgcolor">${
            `<option value="">default</option>` +
            COLORS.map((c) => `<option ${c === page.pageNameColor ? "selected" : ""}>${c}</option>`).join("")
          }</select></div>
        <div class="muted">id: ${page.id}</div>
      </div>
      ${slotHtml}
      <button class="btn ghost" id="addline">+ Add line</button>`;
  }

  /** Rows shown in the editor: all existing lines, padded to at least 6 slots. */
  _editorRows(page) {
    const rows = (page.lines || []).map((l) => l.row).sort((a, b) => a - b);
    let next = rows.length ? rows[rows.length - 1] + 2 : 3;
    while (rows.length < 6) {
      rows.push(next);
      next += 2;
    }
    return rows;
  }

  /** Map a clicked preview display-row to the editor slot (pagination-aware). */
  _slotForDisplayRow(dataRow) {
    const page = this._page();
    if (!page) return null;
    const slotIdx = (dataRow - 3) / 2;
    if (this._previewTotal > 1) {
      const hasContent = (line) =>
        ["left", "right"].some((s) => {
          const d = line[s] && line[s].display;
          return d && (d.source || d.text || d.label);
        });
      const items = (page.lines || []).filter(hasContent);
      const item = items[this._previewOffset * 6 + slotIdx];
      return item ? item.row : null;
    }
    return dataRow;
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

  _renderAreaDialog() {
    const items = (this._areas || [])
      .map((a) => {
        const count = (this._areaEntities[a.area_id] || []).filter(
          (id) => GEN_DOMAINS.includes(id.split(".")[0]) && this._hass.states[id]
        ).length;
        return `<li data-area="${a.area_id}"><span>${escapeHtml(a.name)}</span>
          <span class="muted">${count} entities</span></li>`;
      })
      .join("");
    return `<div class="overlay" id="overlay">
      <div class="dialog">
        <h3>Generate page from area</h3>
        <p class="muted">Creates a page with all supported entities of the area — lights and
        switches first, then climate and sensors. You can edit everything afterwards.</p>
        <ul class="arealist">${items}</ul>
        <div class="toolbar"><button class="btn ghost" id="closedialog">Cancel</button></div>
      </div>
    </div>`;
  }

  // ---- events -------------------------------------------------------

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

    $$(".pagelist li").forEach((li) =>
      li.addEventListener("click", () => {
        this._selectedPageId = li.dataset.page;
        this._previewOffset = 0;
        this._schedulePreview();
        this._render();
      })
    );

    on("#addpage", "click", () => this._addPage());
    on("#addarea", "click", () => this._openAreaDialog());
    on("#delpage", "click", () => this._deletePage());
    on("#save", "click", () => this._save());
    on("#closedialog", "click", () => {
      this._areaDialogOpen = false;
      this._render();
    });
    on("#overlay", "click", (e) => {
      if (e.target.id === "overlay") {
        this._areaDialogOpen = false;
        this._render();
      }
    });

    $$(".arealist li").forEach((li) =>
      li.addEventListener("click", () => {
        const area = this._areas.find((a) => a.area_id === li.dataset.area);
        if (area) this._generateFromArea(area);
      })
    );

    const bindPageProp = (id, apply) => {
      on(id, "change", (e) => {
        apply(e.target.value);
        this._touch();
      });
    };
    bindPageProp("#pgname", (v) => (this._page().name = v));
    bindPageProp("#pgparent", (v) => (this._page().parent = v || null));
    bindPageProp("#pgcolor", (v) => (this._page().pageNameColor = v || undefined));

    $$(".typesel button").forEach((btn) =>
      btn.addEventListener("click", () => {
        const { type, row, side } = btn.dataset;
        const line = this._line(Number(row));
        this._setSideType(line[side], type);
        this._touch();
      })
    );

    $$("input[data-f], select[data-f]").forEach((el) =>
      el.addEventListener("change", (e) => {
        const { f, row, side } = e.target.dataset;
        const line = this._line(Number(row));
        const cfg = line[side];
        const value = e.target.value;
        if (f === "label") cfg.label = value;
        else if (f === "btnTarget") cfg.button.target = value;
        else cfg.display[f] = value;
        this._touch();
      })
    );

    $$("select[data-fk]").forEach((el) =>
      el.addEventListener("change", (e) => {
        const key = e.target.dataset.fk;
        if (e.target.value) this._functionKeys[key] = e.target.value;
        else delete this._functionKeys[key];
        this._dirty = true;
        this._render();
      })
    );

    on("#addline", "click", () => {
      const page = this._page();
      if (!page) return;
      const rows = this._editorRows(page);
      this._line(rows[rows.length - 1] + 2);
      this._touch();
    });

    $$(".delline").forEach((btn) =>
      btn.addEventListener("click", () => {
        const page = this._page();
        const row = Number(btn.dataset.row);
        page.lines = (page.lines || []).filter((l) => l.row !== row);
        this._touch();
      })
    );

    $$(".mcdu pre").forEach((pre) =>
      pre.addEventListener("click", () => {
        const row = Number(pre.dataset.row);
        const dataRow = row % 2 === 0 ? row + 1 : row;
        const slotRow = this._slotForDisplayRow(dataRow);
        const slot = slotRow !== null && this.shadowRoot.querySelector(`#slot-${slotRow}`);
        if (slot) {
          $$(".slot").forEach((s) => s.classList.remove("highlight"));
          slot.classList.add("highlight");
          slot.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      })
    );

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
