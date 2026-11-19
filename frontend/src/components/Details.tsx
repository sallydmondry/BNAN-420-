import { useState } from "react";
import { ExternalLink, Quote } from "lucide-react";
import { ordinal, usd } from "../format";
import { OFFER_COLORS, type CityBudget, type Extracted, type MarketResult, type OfferId, type ParserOut, type PipelineResult, type RecalcResponse, type SourceRef, type TaxResult, type LifestyleResult } from "../types";
import { Card, FieldValue, OfferDot, ScoreBar, SimulatedBadge, Status } from "./ui";

const TABS = ["Offer details", "Taxes", "City budget", "Market & culture", "Lifestyle"] as const;

export default function Details({ result, recalc }: { result: PipelineResult; recalc: RecalcResponse | null }) {
  const ids = result.offer_ids.filter((i) => result.parsed[i]);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Offer details");
  const [offer, setOffer] = useState<OfferId>(ids[0]);
  const p = result.parsed[offer];
  const tax = (recalc?.taxes ?? result.tax?.results ?? []).find((t) => t.offer_id === offer);
  const budget = (recalc?.budgets ?? result.col?.budgets ?? []).find((b) => b.offer_id === offer);
  const market = result.market?.results.find((m) => m.offer_id === offer);
  const life = result.lifestyle?.results.find((l) => l.offer_id === offer);
  return (
    <Card title="The details behind every number" subtitle="Pick an offer and a topic. Each line shows its formula and source.">
      <div className="flex flex-wrap gap-2">
        {ids.map((i) => (
          <button key={i} onClick={() => setOffer(i)} className={`btn border px-3 py-1.5 text-xs ${offer === i ? "text-white" : "bg-white text-navy border-gray-300"}`}
            style={offer === i ? { background: OFFER_COLORS[i], borderColor: OFFER_COLORS[i] } : {}}>
            <OfferDot id={i} /> {result.parsed[i].label} · {result.parsed[i].location.metro_name ?? "city not matched"}
          </button>
        ))}
      </div>
      <div className="mt-4 flex gap-1 overflow-x-auto border-b border-gray-200" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold ${tab === t ? "border-arroyo text-navy" : "border-transparent text-gray-500 hover:text-navy"}`}>{t}</button>
        ))}
      </div>
      <div className="pt-5">
        {tab === "Offer details" && p && <OfferFieldsTab p={p} />}
        {tab === "Taxes" && <TaxTab t={tax} />}
        {tab === "City budget" && <BudgetTab b={budget} />}
        {tab === "Market & culture" && <MarketTab m={market} />}
        {tab === "Lifestyle" && <LifestyleTab l={life} />}
      </div>
    </Card>
  );
}

function Src({ s }: { s: SourceRef | null | undefined }) {
  if (!s) return null;
  const body = <>{s.name}{s.data_year ? ` (${s.data_year})` : ""}</>;
  return (
    <span className="text-xs text-gray-500">
      {!s.real && <SimulatedBadge />} Source: {s.url ? <a className="text-arroyo hover:underline" href={s.url} target="_blank" rel="noreferrer noopener">{body} <ExternalLink className="inline h-3 w-3" /></a> : body}
    </span>
  );
}

function statusChip<T>(f: Extracted<T>) {
  if (f.status === "stated") return <span className="chip bg-navy-50 text-navy">stated</span>;
  if (f.status === "derived") return <span className="chip bg-arroyo-50 text-arroyo">derived</span>;
  if (f.status === "user_entered") return <span className="chip bg-gray-100 text-gray-700">you entered</span>;
  return <span className="chip bg-gray-100 text-gray-500">not stated</span>;
}

function OfferFieldsTab({ p }: { p: ParserOut }) {
  const f = p.fields;
  const money = (v: number) => usd(v);
  const rows: [string, Extracted<unknown>, ((v: never) => string)?][] = [
    ["Company", f.company], ["Job title", f.job_title], ["Office city", f.office_city], ["State", f.office_state],
    ["Base salary", f.base_salary, money as never], ["Signing bonus", f.signing_bonus, money as never],
    ["Bonus target", f.bonus_target_pct, ((v: number) => `${v}% of base`) as never], ["Bonus amount", f.bonus_target_amount, money as never],
    ["401(k) employer contribution", f.match_401k, ((v: { description: string }) => v.description) as never],
    ["Employer HSA", f.hsa_employer_annual, ((v: number) => `${usd(v)}/yr`) as never],
    ["Health premium", f.health_premium_monthly, ((v: number) => `${usd(v)}/mo`) as never],
    ["PTO", f.pto_days, ((v: number) => `${v} days`) as never], ["Relocation", f.relocation, money as never],
    ["Equity", f.equity, ((v: { value_usd: number | null; vesting_years: number | null }) => `${usd(v.value_usd)}${v.vesting_years ? ` over ${v.vesting_years} yrs` : ""}`) as never],
    ["Start date", f.start_date], ["Work arrangement", f.work_arrangement],
  ];
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-3 text-xs text-gray-600">
        <span>Read via: <b>{({ pdf_text: "PDF text", ocr: "offline OCR", text: "text", form: "manual form" } as Record<string, string>)[p.text_source] ?? p.text_source}</b></span>
        <span>Found {p.fields_found}/{p.fields_total} key fields</span>
        <span>Metro: <b>{p.location.metro_name ?? "not matched"}</b>{p.location.basis === "remote_residence" && " (your remote home base)"}</span>
      </div>
      {p.warnings.map((w, i) => <p key={i} className="mb-2"><Status state="warn" label={w} /></p>)}
      <div className="divide-y divide-gray-100">
        {rows.map(([label, field, fmt]) => (
          <div key={label} className="grid gap-1 py-2.5 sm:grid-cols-[200px_1fr_auto] sm:items-start">
            <span className="text-sm font-medium text-gray-600">{label}</span>
            <div>
              <span className="text-sm font-semibold text-gray-900">
                {label === "PTO" && f.pto_unlimited ? "Unlimited / flexible" : <FieldValue f={field} fmt={fmt as ((v: unknown) => string) | undefined} />}
              </span>
              {field.evidence && <p className="mt-0.5 flex gap-1 text-xs italic text-gray-500"><Quote className="h-3 w-3 shrink-0" />{field.evidence}</p>}
              {field.note && <p className="mt-0.5 text-xs text-gray-500">{field.note}</p>}
            </div>
            <span>{label === "PTO" && f.pto_unlimited ? <span className="chip bg-navy-50 text-navy">stated</span> : statusChip(field)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaxTab({ t }: { t: TaxResult | undefined }) {
  if (!t || !t.computed) return <p className="text-sm text-gray-600">Taxes couldn't be computed (salary not stated in offer).</p>;
  return (
    <div>
      {t.explanation && <p className="mb-4 text-sm text-gray-800">{t.explanation}</p>}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Gross salary" v={usd(t.gross_salary)} /><Stat label="Total tax" v={usd(t.total_tax)} />
        <Stat label="Effective rate" v={`${(t.effective_rate * 100).toFixed(1)}%`} /><Stat label="Take-home / mo" v={usd(t.take_home_monthly)} />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {t.lines.map((l) => (
            <tr key={l.label} className="border-b border-gray-100 align-top">
              <td className="py-2.5 pr-3 font-medium text-gray-800">{l.label}</td>
              <td className="py-2.5 pr-3 text-right font-semibold tabular-nums">{usd(l.annual)}/yr</td>
              <td className="py-2.5"><p className="text-xs text-gray-600">{l.formula}</p><Src s={l.source} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-3 list-disc pl-5 text-xs text-gray-500">{t.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
    </div>
  );
}

function BudgetTab({ b }: { b: CityBudget | undefined }) {
  if (!b || !b.computed) return <p className="text-sm text-gray-600">This city isn't in TrueOffer's 52-metro dataset, so a budget couldn't be estimated.</p>;
  return (
    <div>
      {b.explanation && <p className="mb-4 text-sm text-gray-800">{b.explanation}</p>}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Rent / mo" v={usd(b.rent_monthly)} /><Stat label="Living costs / mo" v={usd(b.living_costs_monthly)} />
        <Stat label="Prices vs U.S." v={b.rpp_all ? `${b.rpp_all.toFixed(0)} (US=100)` : "—"} /><Stat label="Rent trend (1 yr)" v={b.zori_yoy_pct !== null ? `${b.zori_yoy_pct > 0 ? "+" : ""}${b.zori_yoy_pct.toFixed(1)}%` : "—"} />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {b.lines.map((l) => (
            <tr key={l.key} className="border-b border-gray-100 align-top">
              <td className="py-2.5 pr-3 font-medium text-gray-800">{l.label}</td>
              <td className="py-2.5 pr-3 text-right font-semibold tabular-nums">{usd(l.monthly)}/mo</td>
              <td className="py-2.5"><p className="text-xs text-gray-600">{l.formula}</p><Src s={l.source} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketTab({ m }: { m: MarketResult | undefined }) {
  if (!m) return <p className="text-sm text-gray-600">Market analysis unavailable.</p>;
  const w = m.wages;
  const pts: [string, number | null, number][] = [["10th", w.p10, 10], ["25th", w.p25, 25], ["Median", w.p50, 50], ["75th", w.p75, 75], ["90th", w.p90, 90]];
  const pos = (pctile: number) => `${Math.max(0, Math.min(100, ((pctile - 10) / 80) * 100))}%`;
  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-gray-800">{m.soc_match_reason} <span className="text-xs text-gray-500">(match confidence {(m.soc_match_confidence * 100).toFixed(0)}%)</span></p>
        {m.salary_percentile !== null && (
          <p className="mt-1 text-lg font-bold text-navy">This salary is around the {ordinal(m.salary_percentile)} percentile of local pay for the role.</p>
        )}
      </div>
      {w.p50 && (
        <div>
          <div className="relative mt-6 h-3 rounded-full bg-gradient-to-r from-gray-200 via-arroyo-100 to-arroyo/60">
            {pts.map(([l, v, q]) => v && (
              <div key={l} className="absolute -top-6 -translate-x-1/2 text-center" style={{ left: pos(q) }}>
                <p className="text-[10px] font-semibold text-gray-500">{l}</p>
              </div>
            ))}
            {pts.map(([l, v, q]) => v && <div key={l + "t"} className="absolute top-0 h-3 w-px bg-white" style={{ left: pos(q) }} />)}
            {m.salary_percentile !== null && (
              <div className="absolute -top-1 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-white bg-brandred shadow" style={{ left: pos(m.salary_percentile) }} title="This offer" />
            )}
          </div>
          <div className="relative mt-2 h-4 text-xs tabular-nums text-gray-500">{pts.map(([l, v, q]) => <span key={l} className="absolute -translate-x-1/2" style={{ left: pos(q) }}>{usd(v)}</span>)}</div>
          <p className="mt-2 text-xs text-gray-500">BLS OEWS May 2025, {w.area_name} ({w.area_level}). Covers all experience levels, so entry-level offers often sit below the median. Red dot = this offer.</p>
        </div>
      )}
      {m.leverage_points.length > 0 && <div><p className="label">Negotiation leverage</p><ul className="list-disc pl-5 text-sm text-gray-700">{m.leverage_points.map((x) => <li key={x}>{x}</li>)}</ul></div>}
      <div className="rounded-xl border border-gray-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-navy">Culture signals</p>
          {m.culture.source === "simulated" ? <SimulatedBadge text="SIMULATED reviews — fictional company" /> : m.culture.source === "user_pasted" ? <span className="chip bg-gray-100 text-gray-700">From reviews you pasted</span> : null}
        </div>
        <p className="mt-1 text-sm text-gray-700">{m.culture.summary}</p>
        {Object.keys(m.culture.themes).length > 0 && (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {Object.entries(m.culture.themes).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-xs"><span className="capitalize text-gray-600">{k.replace("_", "-")}</span><span className="tabular-nums text-gray-500">{v > 0 ? "+" : ""}{v.toFixed(2)}</span></div>
                <ScoreBar value={(v + 1) * 50} color={v >= 0 ? "#0C234B" : "#AB0520"} />
              </div>
            ))}
          </div>
        )}
        {(m.culture.pros.length > 0 || m.culture.cons.length > 0) && (
          <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
            <div><p className="label">Common pros</p><ul className="list-disc pl-5 text-gray-700">{m.culture.pros.map((x) => <li key={x}>{x}</li>)}</ul></div>
            <div><p className="label">Common cons</p><ul className="list-disc pl-5 text-gray-700">{m.culture.cons.map((x) => <li key={x}>{x}</li>)}</ul></div>
          </div>
        )}
      </div>
    </div>
  );
}

function LifestyleTab({ l }: { l: LifestyleResult | undefined }) {
  if (!l || !l.computed) return <p className="text-sm text-gray-600">Lifestyle couldn't be scored for this city.</p>;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <Stat label="Lifestyle fit" v={l.fit_score !== null ? `${l.fit_score.toFixed(0)}/100` : "—"} />
        <ul className="text-sm text-gray-700">{l.highlights.map((h) => <li key={h}>{h}</li>)}</ul>
      </div>
      <div className="space-y-4">
        {l.dimensions.map((d) => (
          <div key={d.dimension} className="grid gap-2 sm:grid-cols-[220px_1fr]">
            <div>
              <p className="text-sm font-semibold text-gray-800">{d.label}</p>
              <p className="text-xs text-gray-500">Your importance: {d.weight}/5</p>
            </div>
            <div>
              <div className="flex items-center gap-3"><span className="w-12 text-sm font-bold tabular-nums">{d.score !== null ? d.score.toFixed(0) : "—"}</span><ScoreBar value={d.score} /></div>
              <p className="mt-1 text-xs text-gray-600">{Object.entries(d.inputs).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "number" ? v.toLocaleString() : v}`).join(" · ")}</p>
              <p className="text-xs text-gray-500">{d.formula}{d.source && ` — ${d.source}`}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: string }) {
  return <div className="rounded-xl bg-gray-50 px-3 py-2"><p className="text-[11px] font-semibold uppercase text-gray-500">{label}</p><p className="text-lg font-bold tabular-nums text-navy">{v}</p></div>;
}
