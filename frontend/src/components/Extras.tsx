import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, ShieldCheck } from "lucide-react";
import type { DecisionOut, OfferId, PipelineResult } from "../types";
import { Card, EngineBadge, OfferDot, SimulatedBadge, Status } from "./ui";

export function Negotiation({ d, result }: { d: DecisionOut; result: PipelineResult }) {
  const [copied, setCopied] = useState(false);
  const [body, setBody] = useState(d.negotiation.body);
  useEffect(() => setBody(d.negotiation.body), [d.negotiation.body]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(`Subject: ${d.negotiation.subject}\n\n${body}`); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* clipboard blocked */ }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
      <Card title="Negotiation email" subtitle={d.negotiation.offer_id ? `Draft for ${result.parsed[d.negotiation.offer_id]?.label ?? "the top offer"}. Edit before sending.` : "No offer to negotiate yet."}
        right={d.negotiation.body ? <button className="btn-ghost px-3 py-1.5 text-xs" onClick={copy}>{copied ? <><Check className="h-3.5 w-3.5" /> Copied</> : <><Copy className="h-3.5 w-3.5" /> Copy</>}</button> : undefined}>
        {d.negotiation.body && (
          <>
            <p className="text-sm"><span className="font-semibold text-gray-500">Subject:</span> {d.negotiation.subject}</p>
            <textarea className="input mt-2 h-64 text-sm leading-relaxed" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Negotiation email" />
            {d.negotiation.evidence.length > 0 && (
              <div className="mt-3"><p className="label">Evidence used</p><ul className="list-disc pl-5 text-xs text-gray-600">{d.negotiation.evidence.map((e) => <li key={e}>{e}</li>)}</ul></div>
            )}
          </>
        )}
      </Card>
      <Card title="Questions to ask each recruiter" subtitle="Based on what each letter didn't say.">
        <div className="space-y-4">
          {Object.entries(d.recruiter_questions).map(([id, qs]) => (
            <div key={id}>
              <p className="flex items-center gap-2 text-sm font-semibold text-navy"><OfferDot id={id as OfferId} /> {result.parsed[id]?.label} — {result.parsed[id]?.fields.company.value ?? "company not stated"}</p>
              <ul className="mt-1 list-disc pl-5 text-sm text-gray-700">{qs.map((q) => <li key={q}>{q}</li>)}</ul>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function UnderTheHood({ result }: { result: PipelineResult }) {
  const [open, setOpen] = useState(false);
  const parsed = Object.values(result.parsed);
  const agents = [
    ...parsed.map((p) => ({ name: `1 · Offer Parser (${p.label})`, a: p })),
    result.tax && { name: "2 · Tax & Take-Home", a: result.tax },
    result.col && { name: "3 · Cost of Living & Housing", a: result.col },
    result.market && { name: "4 · Market & Company", a: result.market },
    result.lifestyle && { name: "5 · Lifestyle Fit", a: result.lifestyle },
    result.decision && { name: "6 · Decision Strategist", a: result.decision },
  ].filter(Boolean) as { name: string; a: { engine: string; confidence: number; elapsed_ms: number; log: string[]; warnings: string[] } }[];
  return (
    <Card title="Under the hood" subtitle={`Six agents, three stages, ${result.total_elapsed_ms.toLocaleString()} ms total. Every agent reports its engine, confidence and what it did.`}
      right={<button className="btn-ghost px-3 py-1.5 text-xs no-print" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} agent logs</button>}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead><tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500"><th className="py-2">Agent</th><th>Status</th><th>Engine</th><th>Confidence</th><th className="text-right">Time</th></tr></thead>
          <tbody>
            {agents.map(({ name, a }) => (
              <tr key={name} className="border-b border-gray-100 align-top">
                <td className="py-2.5 pr-3">
                  <p className="font-medium text-gray-800">{name}</p>
                  {open && <ul className="mt-1 list-disc pl-5 text-xs text-gray-600">{a.log.map((l, i) => <li key={i}>{l}</li>)}</ul>}
                  {a.warnings.map((w, i) => <p key={i} className="mt-1"><Status state="warn" label={w} /></p>)}
                </td>
                <td className="py-2.5 pr-3"><Status state="done" /></td>
                <td className="py-2.5 pr-3"><EngineBadge engine={a.engine === "deterministic" ? "local" : a.engine} /></td>
                <td className="py-2.5 pr-3 tabular-nums">{Math.round(a.confidence * 100)}%</td>
                <td className="py-2.5 text-right tabular-nums text-gray-600">{a.elapsed_ms} ms</td>
              </tr>
            ))}
            {result.degraded_agents.map((g) => (
              <tr key={g}><td className="py-2.5 font-medium">{g}</td><td colSpan={4}><Status state="failed" label="Didn't finish — results shown without it" /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

const SOURCES: [string, string, string][] = [
  ["IRS Rev. Proc. 2025-32 — 2026 brackets & standard deduction", "TY2026", "https://www.irs.gov/pub/irs-drop/rp-25-32.pdf"],
  ["IRS Publication 15 (2026) — Social Security wage base", "2026", "https://www.irs.gov/pub/irs-pdf/p15.pdf"],
  ["Tax Foundation — State individual income tax rates & brackets", "2026", "https://taxfoundation.org/data/all/state/state-income-tax-rates/"],
  ["Zillow Observed Rent Index (ZORI)", "latest month", "https://www.zillow.com/research/data/"],
  ["Census ACS 1-year — rents, commute, age", "2024", "https://www.census.gov/programs-surveys/acs"],
  ["BLS Consumer Expenditure Survey", "2025", "https://www.bls.gov/cex/"],
  ["BEA Regional Price Parities", "2024", "https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area"],
  ["BLS Occupational Employment & Wage Statistics", "May 2025", "https://www.bls.gov/oes/"],
  ["NOAA U.S. Climate Normals", "1991–2020", "https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals"],
  ["Census Gazetteer — place coordinates", "2024", "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html"],
];

export function Sources({ result }: { result: PipelineResult }) {
  return (
    <Card title="Sources & assumptions">
      <div className="grid gap-6 lg:grid-cols-2">
        <ul className="space-y-1.5 text-sm">
          {SOURCES.map(([n, y, u]) => (
            <li key={n}><a className="text-arroyo hover:underline" href={u} target="_blank" rel="noreferrer noopener">{n} <ExternalLink className="inline h-3 w-3" /></a> <span className="text-gray-500">({y})</span></li>
          ))}
          <li className="pt-1"><SimulatedBadge /> <span className="text-gray-600">Employee reviews and sample offer letters are fictional, generated for demonstration.</span></li>
        </ul>
        <div className="space-y-2 text-sm text-gray-700">
          <p className="flex gap-2"><ShieldCheck className="h-5 w-5 shrink-0 text-navy" /> Your offers were processed in memory only. Nothing was saved, and this result expires from the server in 30 minutes.</p>
          <p>Taxes assume tax year 2026, a single filer, the standard deduction, no other income, and that you live in the office city. Rent assumes a 1-bedroom when living alone, or your share of a larger unit with roommates.</p>
          <p>Money math is done by deterministic code — {result.llm_mode === "claude" ? "Claude only writes explanations of numbers it's given." : "no AI model is involved in any number."}</p>
          <p className="font-semibold text-navy">All figures are estimates for comparing offers — not tax, legal or financial advice.</p>
        </div>
      </div>
    </Card>
  );
}
