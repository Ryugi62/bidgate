// Runs the vendored Markovian reference runtime over document chunks.
// stdin: {goal, instructions, fields, chunks:[{lines:[{n,text}]}], llm:{base_url,api_key,model,timeout}}
// stdout: {engine, status, claims, steps:[{step, lines, carryover_in_chars, carryover_level, ok, attempts, error, claims}]}
// Each chunk is one Markovian step: the runtime builds the step prompt (goal + carryover from the previous step),
// our generator turns it into one Nightshift chat completion (one user message) and ends the text with the
// runtime's own [STATE_CHECKPOINT] / [TASK_COMPLETE] markers.
import { Markovian } from "../vendor/markovian/reference/src/index.ts";

const input = JSON.parse(await new Promise((res) => {
  let s = ""; process.stdin.setEncoding("utf8");
  process.stdin.on("data", (d) => (s += d)); process.stdin.on("end", () => res(s));
}));
const { goal, instructions, fields, chunks, llm } = input;
const REQ_S = Math.min(llm.timeout || 90, 90), DEADLINE_MS = Date.now() + (input.deadline_s || 480) * 1000;
const left = () => DEADLINE_MS - Date.now();
const N = chunks.length;
const first = (c) => c.lines[0].n, last = (c) => c.lines[c.lines.length - 1].n;

async function chat(text, lines) {
  const ctl = new AbortController();
  if (left() <= 0) throw new Error("run time limit reached");
  const t = setTimeout(() => ctl.abort(), Math.min(REQ_S * 1000, left()));
  try {
    const r = await fetch(llm.base_url + "/chat/completions", {
      method: "POST", signal: ctl.signal,
      headers: { "Content-Type": "application/json", ...(llm.api_key ? { Authorization: "Bearer " + llm.api_key } : {}) },
      body: JSON.stringify({ model: llm.model, temperature: 0, max_tokens: 600, messages: [{ role: "user", content: text }] }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    const content = String(data.choices[0].message.content).trim();
    return parseAnswer(content, lines).filter((x) => fields.includes(x.field) && Number.isInteger(x.line));
  } finally { clearTimeout(t); }
}

// warm-up: one short call so the local model is loaded before the first chunk (result is recorded, never fatal)
const warmup = { ok: false, attempts: 0, error: "" };
if (input.warmup !== false) {
  for (let a = 1; a <= 3 && !warmup.ok && left() > 0; a++) {
    warmup.attempts = a;
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), Math.min(REQ_S * 1000, left()));
      const r = await fetch(llm.base_url + "/chat/completions", { method: "POST", signal: ctl.signal,
        headers: { "Content-Type": "application/json", ...(llm.api_key ? { Authorization: "Bearer " + llm.api_key } : {}) },
        body: JSON.stringify({ model: llm.model, temperature: 0, max_tokens: 8, messages: [{ role: "user", content: "Reply OK" }] }) });
      clearTimeout(t);
      if (!r.ok) throw new Error("HTTP " + r.status);
      warmup.ok = true; warmup.error = "";
    } catch (e) { warmup.error = String(e.message || e).slice(0, 80); await new Promise((r) => setTimeout(r, 3000)); }
  }
}

const NAMES = [[/^deadline/i, "deadline"], [/^(minimum )?age|^min_age/i, "min_age"], [/^(online|mode|onsite)/i, "mode"],
  [/^fee|^cost|^price/i, "fee"], [/^deliver|^submission/i, "deliverables"]];
// The answer is either JSON {"claims":[...]} or lines "name | line number | words". A cited line that does not hold
// the quote is re-pointed to the chunk line that does (the domain still verifies quote + receipt itself).
function parseAnswer(content, lines) {
  let raw = [];
  try { raw = JSON.parse(content.replace(/^```(?:json)?|```$/gm, "").trim()).claims.map((x) => ({ field: String(x.field), line: Number(x.line), quote: String(x.quote) })); }
  catch {
    for (const row of content.split("\n")) {
      const m = row.replace(/^\s*\d+\.\s*|\*\*/g, "").split("|").map((x) => x.trim());
      if (m.length < 3) continue;
      const hit = NAMES.find(([re]) => re.test(m[0]));
      if (hit) raw.push({ field: hit[1], line: Number(m[1]), quote: m.slice(2).join("|").trim() });
    }
  }
  return raw.map((x) => {
    const own = lines.find((l) => l.n === x.line);
    if (own && own.text.includes(x.quote)) return x;
    const other = lines.find((l) => x.quote && l.text.includes(x.quote));
    return other ? { ...x, line: other.n } : x;
  });
}

const steps = [], claims = [], found = {};
let k = 0;

function stateBlock(done) {
  const list = Object.entries(found).map(([f, ls]) => `${f}@L${[...new Set(ls)].slice(0, 6).join(",")}`).join(" ");
  const missing = fields.filter((f) => !found[f]);
  return (
    `COMPLETED: chunks 1-${done} of ${N} read (lines ${first(chunks[0])}-${last(chunks[done - 1])}); located: ${list || "nothing yet"}\n` +
    `REMAINING: lines ${done < N ? first(chunks[done]) + "-" + last(chunks[N - 1]) : "none"}\n` +
    `DECISIONS: not yet found: ${missing.join(", ") || "none"}\n` +
    `CONTEXT: ${goal.slice(0, 120)}`
  );
}

const generator = async (prompt) => {
  const i = k++, c = chunks[i];
  const m = prompt.match(/\[CARRYOVER STATE\]\n([\s\S]*?)\n\nContinue exactly/);
  const carry = m ? m[1] : "";
  const numbered = c.lines.map((l) => `${l.n}\t${l.text}`).join("\n");
  const user = instructions + (carry ? `\n\nEarlier chunks of the same document (compressed state):\n${carry}` : "") + "\n\n" + numbered;
  const rec = { step: i + 1, lines: [first(c), last(c)], carryover_in_chars: carry.length, ok: false, attempts: 0, error: "", claims: 0 };
  let got = [];
  for (let a = 1; a <= 2 && !rec.ok; a++) {
    rec.attempts = a;
    try { got = await chat(user, c.lines); rec.ok = true; rec.error = ""; }
    catch (e) { rec.error = String(e.message || e).slice(0, 120); }
  }
  rec.claims = got.length;
  for (const g of got) { claims.push(g); (found[g.field] ||= []).push(g.line); }
  steps.push(rec);
  const body = JSON.stringify({ claims: got });
  return { text: body + "\n" + (i + 1 < N ? "[STATE_CHECKPOINT]\n" + stateBlock(i + 1) : "[TASK_COMPLETE]") };
};

const engine = new Markovian({ chunkConfig: { chunkSize: 2000, maxChunks: Math.max(1, Math.min(32, N)), carryoverTokens: 300 }, generator });
const run = await engine.run({ goal, reflect: false });
run.chunks.forEach((ch, i) => {
  if (steps[i]) { steps[i].carryover_level = i === 0 ? "none" : "marker"; steps[i].carryover_in_tokens_est = Math.ceil(ch.carryover.length / 4); }
});
process.stdout.write(JSON.stringify({
  engine: "Meterless Markovian reference runtime, vendor/markovian/reference/src (node " + process.version + ")",
  status: run.status, runtime_chunks: run.chunks.length, efficiency_percent_estimated: run.efficiencyPercent,
  warmup, deadline_s: input.deadline_s || 480, claims, steps,
}));
