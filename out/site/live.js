// Live extraction with the visitor's own Anthropic API key.
// Same system prompt, JSON schema and effort as the Python pipeline (shipped in live.json by
// navigator/site.py), plus a port of navigator/extract/verify.py: a quote counts only if it is found
// verbatim in the document (whitespace and typographic quotes/dashes normalized, nothing fuzzy).
// The key lives in this page's memory only: it is never stored and is sent only to api.anthropic.com.

const SDK_URL = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.131.0/+esm";
const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5"];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const T = {
  en: {
    intro: "Run the extraction step yourself on any corpus document or a new ordinance, with your own Anthropic API key. It uses the same prompt and JSON schema as the pipeline, then checks every quote word for word against the document.",
    keynote: "Your key stays in this tab's memory: it is never saved and is sent only to api.anthropic.com, directly from your browser. Usage is billed to your Anthropic account (one document is typically a few cents).",
    key: "Anthropic API key", model: "Model", doc: "Document", paste: "Paste a new document…",
    docid: "Document id", title: "Title", hint: "Jurisdiction hint (e.g. \"Cambridge, MA\")", text: "Document text",
    run: "Extract rules", running: "Extracting… (this can take a minute)", none: "No rules in scope were found in this document.",
    verified: "quote verified verbatim", fragment: "quote verified (exact sentence from the model's quote)",
    unverified: "quote NOT found in the document: the pipeline would skip this rule",
    addrs: "sample addresses in this jurisdiction", outside: "jurisdiction outside the sample address set",
    truncated: "Document is longer than one extraction chunk; only the first part was sent.",
    covnote: "Coverage conditions (year built, units, exemptions) are evaluated per address by the Python pipeline; this panel shows which sample addresses fall in the rule's jurisdiction.",
    needkey: "Enter your API key first.", needtext: "Paste the document text first.", usage: "tokens in / out",
  },
  es: {
    intro: "Ejecute usted mismo el paso de extracción sobre cualquier documento del corpus o una nueva ordenanza, con su propia clave de API de Anthropic. Usa el mismo prompt y esquema JSON que el pipeline y verifica cada cita palabra por palabra.",
    keynote: "Su clave queda solo en la memoria de esta pestaña: nunca se guarda y solo se envía a api.anthropic.com, directamente desde su navegador. El uso se cobra a su cuenta de Anthropic (un documento suele costar unos centavos).",
    key: "Clave de API de Anthropic", model: "Modelo", doc: "Documento", paste: "Pegar un documento nuevo…",
    docid: "Id del documento", title: "Título", hint: "Jurisdicción (p. ej. \"Cambridge, MA\")", text: "Texto del documento",
    run: "Extraer reglas", running: "Extrayendo… (puede tardar un minuto)", none: "No se encontraron reglas en este documento.",
    verified: "cita verificada textualmente", fragment: "cita verificada (oración exacta de la cita del modelo)",
    unverified: "la cita NO aparece en el documento: el pipeline omitiría esta regla",
    addrs: "direcciones de muestra en esta jurisdicción", outside: "jurisdicción fuera del conjunto de direcciones",
    truncated: "El documento supera un fragmento de extracción; solo se envió la primera parte.",
    covnote: "Las condiciones de cobertura (año, unidades, exenciones) se evalúan por dirección en el pipeline de Python; este panel muestra qué direcciones están en la jurisdicción de la regla.",
    needkey: "Primero ingrese su clave de API.", needtext: "Primero pegue el texto del documento.", usage: "tokens entrada / salida",
  },
};
const t = (k) => (T[document.documentElement.lang] || T.en)[k];

// ---- citation lock (port of navigator/extract/verify.py) ----
const TRANS = { "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " " };
const tr = (s) => s.replace(/[‘’“”–— ]/g, (c) => TRANS[c]);
function normalizeWithMap(s) {
  const src = tr(s); let out = ""; const idx = []; let prevSpace = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (/\s/.test(ch)) { if (prevSpace) continue; out += " "; idx.push(i); prevSpace = true; }
    else { out += ch; idx.push(i); prevSpace = false; }
  }
  return [out, idx];
}
function locate(quote, text) {
  if (!quote || !text) return null;
  const q = tr(quote).trim().split(/\s+/).join(" ");
  if (q.length < 20) return null;
  const [norm, idx] = normalizeWithMap(text);
  const pos = norm.indexOf(q);
  if (pos < 0) return null;
  return [idx[pos], idx[pos + q.length - 1] + 1];
}
function lockQuote(quote, text) {
  const span = locate(quote, text);
  if (span) return { quote: text.slice(...span), method: "verbatim" };
  const frags = (quote || "").split(/(?<=[.;:])\s+/).sort((a, b) => b.length - a.length);
  for (const f of frags) {
    if (f.length < 60) break;
    const s = locate(f, text);
    if (s) return { quote: text.slice(...s), method: "verbatim_fragment" };
  }
  return { quote: null, method: "unverified" };
}

// ---- jurisdiction -> sample addresses ----
function jurisdictionId(L, r) {
  const st = (r.jurisdiction_state || "").toUpperCase();
  if (!L.jurisdictions[st]) return null;
  if (r.jurisdiction_level === "state") return st;
  const name = (r.jurisdiction_name || "").toLowerCase()
    .replace(/^(the\s+)?(city and county|city|town|township|borough)\s+of\s+/, "").replace(/,.*$/, "").trim();
  return L.jurisdictions[st][name] || null;
}

let LIVE = null;
async function loadLive() {
  if (!LIVE) LIVE = await (await fetch("live.json")).json();
  return LIVE;
}

function texts() {
  $("lv-intro").textContent = t("intro"); $("lv-keynote").textContent = t("keynote");
  for (const k of ["key", "model", "doc", "docid", "title", "hint", "text"]) $("lv-" + k + "-l").textContent = t(k);
  $("lv-run").textContent = t("run");
  const opt = $("lv-doc").querySelector('option[value=""]'); if (opt) opt.textContent = t("paste");
}

function selectedDoc(L) {
  const id = $("lv-doc").value;
  if (id) return L.docs.find((d) => d.doc_id === id);
  return { doc_id: $("lv-docid").value.trim() || "pasted", title: $("lv-title").value.trim() || "Pasted document",
           url: null, retrieval_date: null, jurisdiction_hint: $("lv-hint").value.trim() || null, text: $("lv-text").value };
}

function renderRules(L, doc, rules, notes) {
  const D = window.NAV_DATA;
  let h = notes.map((n) => `<p class="small" style="color:var(--unk)">${esc(n)}</p>`).join("");
  if (!rules.length) h += `<p class="muted">${t("none")}</p>`;
  for (const r of rules) {
    const lock = lockQuote(r.quote, doc.text);
    const jid = jurisdictionId(L, r);
    const n = jid && D ? D.addresses.filter((a) => (a.stack || []).includes(jid)).length : 0;
    const qbadge = lock.method === "verbatim" ? `<span class="badge b-applies">${t("verified")}</span>`
      : lock.method === "verbatim_fragment" ? `<span class="badge b-applies">${t("fragment")}</span>`
      : `<span class="badge b-flag">${t("unverified")}</span>`;
    h += `<div class="rule"><span class="badge b-${r.status === "enacted" ? "applies" : r.status === "pending" ? "pending" : "superseded"}">${esc(r.status)}</span>
      <b>${esc(r.citation)}</b> <span class="muted small">· ${esc(r.jurisdiction_name)}, ${esc(r.jurisdiction_state)} (${esc(r.jurisdiction_level)}) · ${esc(r.category)}${r.effective_date ? " · " + esc(r.effective_date) : ""}</span>
      <div>${esc(document.documentElement.lang === "es" && r.requirement_es ? r.requirement_es : r.requirement)}</div>
      ${r.key_value ? `<div class="small">Key value: <span class="kv">${esc(r.key_value)}</span></div>` : ""}
      ${r.coverage_text ? `<div class="small muted">${esc(r.coverage_text)}</div>` : ""}
      <div class="small">${jid ? `${n} ${t("addrs")} (${esc(jid)})` : t("outside")} · confidence ${esc(r.confidence)}</div>
      <div style="margin-top:6px">${qbadge}</div>
      ${lock.quote ? `<blockquote>${esc(lock.quote)}</blockquote>` : `<blockquote class="muted">${esc(r.quote)}</blockquote>`}</div>`;
  }
  $("lv-out").innerHTML = `<div class="cat">${h}<p class="small muted">${t("covnote")}</p></div>`;
}

async function run() {
  const L = await loadLive();
  const key = $("lv-key").value.trim();
  if (!key) { $("lv-status").textContent = t("needkey"); return; }
  const doc = selectedDoc(L);
  if (!doc || !doc.text.trim()) { $("lv-status").textContent = t("needtext"); return; }
  const notes = [];
  let body = doc.text;
  if (body.length > L.max_chars) { body = body.slice(0, L.max_chars); notes.push(t("truncated")); }
  const user = `Document id: ${doc.doc_id}\nTitle: ${doc.title}\nURL: ${doc.url}\nJurisdiction hint: ${doc.jurisdiction_hint}\nPart: 1/1\n\n<document>\n${body}\n</document>`;
  $("lv-run").disabled = true; $("lv-status").textContent = t("running"); $("lv-out").innerHTML = "";
  try {
    const { default: Anthropic } = await import(SDK_URL);
    const client = new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true });
    const msg = await client.messages.stream({
      model: $("lv-model").value,
      max_tokens: 64000,
      system: [{ type: "text", text: L.system }],
      messages: [{ role: "user", content: user }],
      output_config: { effort: L.effort, format: { type: "json_schema", schema: L.schema } },
      fallbacks: "default",
    }, { headers: { "anthropic-beta": "server-side-fallback-2026-07-01" } }).finalMessage();
    if (msg.stop_reason === "refusal") throw new Error("The model declined this request" + (msg.stop_details?.explanation ? ": " + msg.stop_details.explanation : "."));
    if (msg.stop_reason === "max_tokens") throw new Error("The output was cut off (max_tokens).");
    const textBlock = msg.content.find((b) => b.type === "text");
    if (!textBlock) throw new Error("No text in the response.");
    const out = JSON.parse(textBlock.text);
    renderRules(L, doc, out.rules || [], notes);
    $("lv-status").textContent = `${msg.model} · ${t("usage")}: ${msg.usage.input_tokens} / ${msg.usage.output_tokens} · prompt ${L.prompt_version}`;
  } catch (e) {
    $("lv-status").textContent = "Error: " + (e?.error?.error?.message || e?.message || String(e));
  } finally {
    $("lv-run").disabled = false;
  }
}

async function init() {
  $("lv-model").innerHTML = MODELS.map((m) => `<option>${esc(m)}</option>`).join("");
  const L = await loadLive();
  $("lv-doc").innerHTML = `<option value=""></option>` + L.docs.map((d) =>
    `<option value="${esc(d.doc_id)}">${esc(d.doc_id)} · ${esc(d.title).slice(0, 80)}</option>`).join("");
  const syncPaste = () => { $("lv-paste").hidden = $("lv-doc").value !== ""; };
  $("lv-doc").addEventListener("change", syncPaste); syncPaste();
  $("lv-run").addEventListener("click", run);
  texts();
  new MutationObserver(texts).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
}

let started = false;
window.addEventListener("nav:live-open", () => { if (!started) { started = true; init(); } });
