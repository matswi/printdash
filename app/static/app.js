"use strict";

const POLL_MS = 2000;
const $ = (sel, root = document) => root.querySelector(sel);

const state = {
  which: "not-completed",
  printers: [],
  file: null,
  selectedPrinter: null,
  busy: false,
};

const PRINTER_LABEL = { idle: "Redo", processing: "Skriver ut", stopped: "Pausad", unknown: "Okänd" };
const JOB_LABEL = {
  pending: "Väntar", held: "Pausad", processing: "Skriver ut", stopped: "Stoppad",
  canceled: "Avbruten", aborted: "Misslyckad", completed: "Klar", unknown: "Okänd",
};

// --- API -------------------------------------------------------------------
async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  let body = null;
  try { body = await res.json(); } catch { /* empty response */ }
  if (!res.ok) {
    const detail = body && body.detail;
    throw new Error(typeof detail === "string" ? detail : `Fel ${res.status}`);
  }
  return body;
}
const post = (path, body) => api(path, { method: "POST", body });

// --- Helpers -----------------------------------------------------------------
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3000);
}

const rtf = new Intl.RelativeTimeFormat("sv", { numeric: "auto" });
function ago(ts) {
  if (!ts) return "";
  const s = Math.round(ts - Date.now() / 1000);
  const abs = Math.abs(s);
  if (abs < 45) return "nyss";
  if (abs < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(s / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(s / 86400), "day");
  return new Date(ts * 1000).toLocaleDateString("sv-SE");
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("data-")) node.setAttribute(k, v);
    else node[k] = v;
  }
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function setConn(ok, text) {
  $("#conn").dataset.state = ok ? "ok" : "error";
  $("#conn-text").textContent = text;
}

// --- Printers ----------------------------------------------------------------
function renderPrinters() {
  const root = $("#printers");
  if (!state.printers.length) {
    root.replaceChildren(el("div", { class: "card empty" },
      el("strong", {}, "Inga skrivare hittades"),
      "Lägg till en skrivare i CUPS så dyker den upp här."));
    return;
  }
  const tpl = $("#printer-tpl");
  const openMenu = root.querySelector("details[open]")?.closest("[data-name]")?.dataset.name;
  const nodes = state.printers.map((p) => {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.name = p.name;
    $(".p-name", node).textContent = p.info || p.name;
    $(".p-default", node).hidden = !p.is_default;
    $(".p-sub", node).textContent = [p.make_and_model, p.location].filter(Boolean).join(" · ");
    const pill = $(".p-state", node);
    pill.dataset.s = p.state;
    pill.textContent = PRINTER_LABEL[p.state] || p.state;
    const msg = [p.state_message, ...p.state_reasons.map(humanReason)].filter(Boolean).join(" · ");
    $(".p-message", node).textContent = msg;
    $(".p-queue", node).textContent =
      p.active_jobs === 0 ? "Kön är tom" : p.active_jobs === 1 ? "1 jobb i kön" : `${p.active_jobs} jobb i kön`;
    const toggle = $('[data-act="toggle"]', node);
    toggle.textContent = p.state === "stopped" ? "Återuppta" : "Pausa";
    toggle.dataset.act = p.state === "stopped" ? "resume" : "pause";
    $('[data-act="default"]', node).hidden = p.is_default;
    $('[data-act="cancel-all"]', node).disabled = p.active_jobs === 0;
    if (p.name === openMenu) $("details", node).open = true;
    return node;
  });
  root.replaceChildren(...nodes);
}

function humanReason(r) {
  const base = r.replace(/-(report|warning|error)$/, "");
  const map = {
    "media-empty": "Slut på papper",
    "media-jam": "Papperstrassel",
    "toner-low": "Lite toner",
    "toner-empty": "Slut på toner",
    "door-open": "Luckan är öppen",
    "offline": "Inte ansluten",
    "paused": "",
    "cups-missing-filter": "Drivrutin saknas",
  };
  return base in map ? map[base] : r;
}

function renderPrinterSelect() {
  const sel = $("#printer-select");
  const current = sel.value || state.selectedPrinter;
  const options = state.printers.map((p) =>
    el("option", { value: p.name, disabled: !p.accepting_jobs }, p.info || p.name));
  sel.replaceChildren(...options);
  const fallback = state.printers.find((p) => p.is_default)?.name || state.printers[0]?.name;
  sel.value = state.printers.some((p) => p.name === current) ? current : fallback || "";
  state.selectedPrinter = sel.value;
  updatePrintButton();
}

$("#printers").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const name = btn.closest("[data-name]").dataset.name;
  const act = btn.dataset.act;
  btn.closest("details")?.removeAttribute("open");
  if (act === "cancel-all" && !confirm("Avbryt alla jobb i kön för den här skrivaren?")) return;
  btn.disabled = true;
  try {
    await post(`/api/printers/${encodeURIComponent(name)}/${act}`);
    const msg = {
      pause: "Skrivaren är pausad", resume: "Skrivaren är igång igen",
      testpage: "Testsida skickad", default: "Ny standardskrivare", "cancel-all": "Kön är tömd",
    }[act];
    toast(msg);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    refresh();
  }
});

document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((d) => {
    if (!d.contains(e.target)) d.removeAttribute("open");
  });
});

// --- Queue ---------------------------------------------------------------------
function jobActions(j) {
  const b = (act, label, cls = "") => el("button", { class: `btn btn-ghost ${cls}`, "data-act": act, "data-id": String(j.id) }, label);
  switch (j.state) {
    case "pending": return [b("hold", "Pausa"), b("cancel", "Avbryt", "danger")];
    case "held": return [b("release", "Släpp"), b("cancel", "Avbryt", "danger")];
    case "processing":
    case "stopped": return [b("cancel", "Avbryt", "danger")];
    default: return [b("restart", "Skriv ut igen")];
  }
}

function renderJobs(jobs) {
  const root = $("#jobs");
  if (!jobs.length) {
    root.replaceChildren(state.which === "not-completed"
      ? el("div", { class: "empty" }, el("strong", {}, "Inget i kön"), "Allt är utskrivet.")
      : el("div", { class: "empty" }, el("strong", {}, "Ingen historik än"), "Avslutade jobb visas här."));
    return;
  }
  const printerName = (n) => state.printers.find((p) => p.name === n)?.info || n;
  const rows = jobs.map((j) => {
    const when = j.state === "completed" || j.state === "canceled" || j.state === "aborted"
      ? ago(j.completed || j.created) : ago(j.created);
    const pages = j.state === "processing" && j.pages_done ? `${j.pages_done} sid. klara` : "";
    const meta = [printerName(j.printer), j.user, when, pages, `#${j.id}`].filter(Boolean).join(" · ");
    return el("div", { class: "job" },
      el("div", { class: "job-info" },
        el("div", { class: "job-title", title: j.title }, j.title),
        el("div", { class: "job-meta" }, meta)),
      el("span", { class: "pill", "data-s": j.state }, JOB_LABEL[j.state] || j.state),
      el("div", { class: "job-actions" }, ...jobActions(j)));
  });
  root.replaceChildren(...rows);
}

$("#jobs").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  btn.disabled = true;
  try {
    await post(`/api/jobs/${btn.dataset.id}/${btn.dataset.act}`);
    const msg = { cancel: "Jobbet avbröts", hold: "Jobbet pausades", release: "Jobbet släpptes", restart: "Jobbet skickas igen" }[btn.dataset.act];
    toast(msg);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    refresh();
  }
});

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    state.which = tab.dataset.which;
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
    $("#jobs").replaceChildren();
    refresh();
  }));

// --- Print form ----------------------------------------------------------------
const drop = $("#drop");
const fileInput = $("#file");

function setFile(file) {
  state.file = file || null;
  drop.classList.toggle("has-file", !!file);
  $("#drop-title").textContent = file ? file.name : "Släpp en fil här";
  $("#drop-sub").textContent = file
    ? `${(file.size / 1024 / 1024).toFixed(file.size > 1024 * 1024 ? 1 : 2)} MB · klicka för att byta`
    : "eller klicka för att välja · PDF, bild eller text";
  updatePrintButton();
}

function updatePrintButton() {
  $("#print-btn").disabled = !state.file || !$("#printer-select").value || state.busy;
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f) setFile(f);
});
// Allow dropping a file anywhere on the page
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  if (!drop.contains(e.target) && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});

$("#printer-select").addEventListener("change", (e) => { state.selectedPrinter = e.target.value; updatePrintButton(); });

document.querySelectorAll(".stepper button").forEach((b) =>
  b.addEventListener("click", () => {
    const input = $("#copies");
    input.value = Math.min(99, Math.max(1, (parseInt(input.value, 10) || 1) + Number(b.dataset.step)));
  }));

$("#print-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.file) return;
  const form = new FormData(e.target);
  form.set("file", state.file, state.file.name);
  if (!form.get("fit_to_page")) form.set("fit_to_page", "false");
  state.busy = true;
  const btn = $("#print-btn");
  btn.textContent = "Skickar…";
  updatePrintButton();
  try {
    const res = await post("/api/print", form);
    toast(`Skickat till skrivaren (jobb #${res.job_id})`);
    fileInput.value = "";
    setFile(null);
    e.target.reset();
    $("#printer-select").value = state.selectedPrinter;
  } catch (err) {
    toast(err.message, "error");
  } finally {
    state.busy = false;
    btn.textContent = "Skriv ut";
    updatePrintButton();
    refresh();
  }
});

// --- Polling -------------------------------------------------------------------
let timer = null;
let inflight = false;

async function refresh() {
  if (inflight) return;
  inflight = true;
  try {
    const [printers, jobs, active] = await Promise.all([
      api("/api/printers"),
      api(`/api/jobs?which=${state.which}`),
      state.which === "not-completed" ? null : api("/api/jobs?which=not-completed"),
    ]);
    state.printers = printers;
    renderPrinters();
    renderPrinterSelect();
    renderJobs(jobs);
    const n = (active || jobs).length;
    $("#active-count").textContent = n ? String(n) : "";
    setConn(true, "Ansluten");
  } catch (err) {
    setConn(false, "Ingen kontakt med servern");
  } finally {
    inflight = false;
  }
}

function schedule() {
  clearInterval(timer);
  if (!document.hidden) timer = setInterval(refresh, POLL_MS);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); schedule(); });

api("/api/health").then((h) => { $("#mock-badge").hidden = !h.mock; }).catch(() => {});
refresh();
schedule();
