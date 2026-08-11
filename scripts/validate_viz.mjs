#!/usr/bin/env node
// Validate the datapage's in-browser aggregation logic outside the browser:
// extract the shipped JS from components/_vizlib.qmd, run the same
// aggregation as viz.qmd over the built slices, and write results for
// comparison against an independent R reference (scripts/validate_viz.R).
//
// Usage: node scripts/validate_viz.mjs [dataset] [out.json]

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

// pull the OJS declarations out of the qmd fences and make them valid JS
const qmd = readFileSync(join(ROOT, "components/_vizlib.qmd"), "utf8");
const code = qmd
  .split("\n")
  .filter((l) => !l.startsWith("```") && !l.startsWith("//|"))
  .join("\n")
  .replace(/^STEP_MS = /m, "var STEP_MS = ")
  .replace(/^aoiNames = /m, "var aoiNames = ");
const lib = {};
new Function(
  "exportsObj",
  code +
    "\nObject.assign(exportsObj, {lgamma, incBeta, betaQuantile, bayesCI, " +
    "trialRT, makeAgeBinner, STEP_MS});"
)(lib);
const { bayesCI, trialRT, makeAgeBinner, STEP_MS } = lib;

const dataset = process.argv[2] || "pomper_saffran_2016";
const outPath = process.argv[3] || join(ROOT, "migration/staging/logs/validate_js.json");
const s = JSON.parse(
  readFileSync(join(ROOT, "slices/datasets", `${dataset}.json`), "utf8"));

// mirror viz.qmd defaults: ages 0-84, all words -> "All", 2 age bins,
// plot window (-500, 4000) exclusive, analysis window [250, 2250] inclusive,
// include lab-excluded trials
const adminById = new Map(s.admins.map((a) => [a[0], a]));
const trialById = new Map(s.trials.map((t) => [t[0], t]));
const rows = [];
for (const [aid, tid, t0, runs] of s.runs) {
  const admin = adminById.get(aid);
  if (!admin || admin[1] == null || admin[1] < 0 || admin[1] > 84) continue;
  if (!trialById.has(tid)) continue;
  rows.push({ aid, tid, t0, runs, age: admin[1] });
}
const binner = makeAgeBinner(
  Array.from(new Set(rows.map((r) => r.age))), 2);
for (const r of rows) r.bin = binner.labels[binner.bin(r.age)];

// profile
const acc = new Map();
for (const r of rows) {
  let t = r.t0;
  for (const [aoi, len] of r.runs) {
    for (let k = 0; k < len; k++, t += STEP_MS) {
      if (t <= -500 || t >= 4000 || aoi > 1) continue;
      const key = `${t}|${r.bin}`;
      let e = acc.get(key);
      if (!e) acc.set(key, (e = { t, bin: r.bin, n: 0, p: 0 }));
      e.n += 1;
      if (aoi === 0) e.p += 1;
    }
  }
}
const profile = Array.from(acc.values(), (e) => {
  const [lo, hi] = bayesCI(e.p, e.n);
  return { t: e.t, bin: e.bin, n: e.n, p: e.p,
           prop: e.p / e.n, ci_lower: lo, ci_upper: hi };
}).sort((a, b) => a.t - b.t || a.bin.localeCompare(b.bin));

// accuracy per trial then per bin
const perTrial = [];
for (const r of rows) {
  let t = r.t0, n = 0, p = 0;
  for (const [aoi, len] of r.runs) {
    for (let k = 0; k < len; k++, t += STEP_MS) {
      if (t < 250 || t > 2250 || aoi > 1) continue;
      n += 1;
      if (aoi === 0) p += 1;
    }
  }
  if (n > 0) perTrial.push({ bin: r.bin, prop: p / n });
}
const accuracy = [];
for (const bin of binner.labels) {
  const g = perTrial.filter((d) => d.bin === bin);
  if (!g.length) continue;
  const mean = g.reduce((a, d) => a + d.prop, 0) / g.length;
  const sd = Math.sqrt(
    g.reduce((a, d) => a + (d.prop - mean) ** 2, 0) / (g.length - 1));
  accuracy.push({ bin, n_trials: g.length, mean, sem: sd / Math.sqrt(g.length) });
}

// RT (D-T only)
const rts = [];
for (const r of rows) {
  const res = trialRT(r.t0, r.runs);
  if (res && res.rt != null && res.shift_type === "D-T") {
    rts.push({ bin: r.bin, rt: res.rt });
  }
}
const rtMeans = [];
for (const bin of binner.labels) {
  const g = rts.filter((d) => d.bin === bin);
  if (!g.length) continue;
  const mean = g.reduce((a, d) => a + d.rt, 0) / g.length;
  rtMeans.push({ bin, n: g.length, mean_rt: mean });
}

writeFileSync(outPath, JSON.stringify(
  { dataset, binLabels: binner.labels, profile, accuracy, rtMeans }, null, 1));
console.log(`${dataset}: ${profile.length} profile points, ` +
  `${rts.length} D-T RTs, bins ${binner.labels.join(" / ")}`);
