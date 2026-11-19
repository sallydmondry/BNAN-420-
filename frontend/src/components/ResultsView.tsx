import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ArrowLeft, Printer, RotateCcw, Scale, Trophy } from "lucide-react";
import { recalculate } from "../api";
import { ordinal, usd } from "../format";
import { OFFER_COLORS, type OfferId, type PipelineResult, type Profile, type RecalcResponse, type Row } from "../types";
import { Card, EngineBadge, OfferDot, OfferTag, ScoreBar, SimulatedBadge, Slider, Status } from "./ui";
import Details from "./Details";
import { Negotiation, Sources, UnderTheHood } from "./Extras";

export default function ResultsView({ result, onRestart }: { result: PipelineResult; onRestart: () => void }) {
  const d = result.decision;
  const base = result.profile;
  const [what, setWhat] = useState<Partial<Profile>>({});
  const [recalc, setRecalc] = useState<RecalcResponse | null>(null);
  const [recalcErr, setRecalcErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!result.recalc_context || Object.keys(what).length === 0) { setRecalc(null); return; }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      recalculate(result.recalc_context!, what as Record<string, unknown>).then((r) => { setRecalc(r); setRecalcErr(null); }).catch((e) => setRecalcErr(e.message));
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [what, result.recalc_context]);

  if (!d) {
    return (
      <Card title="We couldn't finish this comparison">
        <p className="text-gray-600">{result.errors.join(" ") || "None of the offers could be read."}</p>
        {Object.values(result.parsed).flatMap((p) => p.warnings).map((w, i) => <p key={i} className="mt-2"><Status state="warn" label={w} /></p>)}
        <button className="btn-primary mt-4" onClick={onRestart}><ArrowLeft className="h-4 w-4" /> Try again</button>
      </Card>
    );
  }

  const rows = recalc?.scorecard ?? d.scorecard;
  const winner = recalc ? recalc.winner : d.winner;
  const tie = recalc ? recalc.is_tie : d.is_tie;
  const headline = recalc?.headline ?? d.headline;
  const sorted = [...rows].sort((a, b) => (a.rank ?? 9) - (b.rank ?? 9));
  const eff = { ...base, ...what, weights: { ...base.weights, ...(what.weights ?? {}) } } as Profile;

  return (
    <div className="min-w-0 space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <button className="btn-ghost" onClick={onRestart}><ArrowLeft className="h-4 w-4" /> Compare different offers</button>
        <div className="flex items-center gap-2">
          <EngineBadge engine={result.llm_mode === "claude" ? "claude" : "local"} />
          <button className="btn-ghost" onClick={() => window.print()}><Printer className="h-4 w-4" /> Save as PDF</button>
        </div>
      </div>

      {/* Headline */}
      <section className="card overflow-hidden">
        <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-center sm:p-8" style={{ borderTop: `6px solid ${winner ? OFFER_COLORS[winner] : "#0C234B"}` }}>
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-white" style={{ background: winner ? OFFER_COLORS[winner] : "#0C234B" }}>
            {tie ? <Scale className="h-7 w-7" /> : <Trophy className="h-7 w-7" />}
          </div>
          <div className="flex-1">
            <p className="text-xs font-bold uppercase tracking-widest text-gray-500">{tie ? "Too close to call" : "Best overall for you"}{recalc && " · with your what-if changes"}</p>
            <h1 className="mt-1 text-xl font-extrabold leading-snug text-navy sm:text-2xl">{headline}</h1>
            <p className="mt-2 text-sm text-gray-600">{d.confidence_note}</p>
            {result.degraded && <p className="mt-2"><Status state="warn" label={`Partial result: ${result.degraded_agents.join(", ")} didn't finish.`} /></p>}
          </div>
          {winner && (recalc?.monthly_advantage ?? d.monthly_advantage) !== null && (
            <div className="rounded-2xl bg-navy-50 px-5 py-4 text-center">
              <p className="text-xs font-semibold uppercase text-gray-500">Monthly difference</p>
              <p className="text-3xl font-extrabold tabular-nums text-navy">{usd(recalc?.monthly_advantage ?? d.monthly_advantage, { sign: true })}</p>
              <p className="text-xs text-gray-500">left over vs. runner-up</p>
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-6">
          <MoneyChart rows={sorted} />
          <OfferCards rows={sorted} winner={winner} result={result} />
          <Scorecard rows={sorted} />
        </div>
        <div className="min-w-0 space-y-6">
          <WhatIf profile={eff} base={base} set={(p) => setWhat({ ...what, ...p })} reset={() => setWhat({})} active={Object.keys(what).length > 0} err={recalcErr} />
          <Card title="What would flip the decision?" subtitle="We re-ran the same math under different assumptions.">
            <ul className="space-y-3">
              {d.sensitivity.map((s) => (
                <li key={s.lever} className="flex gap-2 text-sm">
                  <span className="mt-0.5">{s.flips ? <Status state="warn" label="" /> : <Status state="done" label="" />}</span>
                  <span className={s.flips ? "font-medium text-gray-900" : "text-gray-600"}>{s.statement}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Card title="Why" subtitle="Every number below is computed from your inputs and public data.">
        <p className="text-gray-800">{d.recommendation}</p>
        <ul className="mt-4 space-y-2">
          {d.reasoning.map((r, i) => <li key={i} className="flex gap-2 text-sm text-gray-700"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-arroyo" />{r}</li>)}
        </ul>
      </Card>

      <Details result={result} recalc={recalc} />
      <Negotiation d={d} result={result} />
      <UnderTheHood result={result} />
      <Sources result={result} />
    </div>
  );
}

function MoneyChart({ rows }: { rows: Row[] }) {
  const data = rows.map((r) => ({
    name: `${r.label} · ${r.metro_name}`, id: r.offer_id,
    Taxes: r.taxes_monthly ?? 0, "401(k) & health (pre-tax)": r.pretax_savings_monthly ?? 0,
    Rent: r.rent_monthly ?? 0, "Living costs": r.living_costs_monthly ?? 0, "Loans & other": r.loans_monthly + r.extras_monthly,
    "Left over": Math.max(0, r.left_over_monthly ?? 0), short: Math.min(0, r.left_over_monthly ?? 0),
  }));
  const segs: [string, string][] = [["Taxes", "#9CA3AF"], ["401(k) & health (pre-tax)", "#D1D5DB"], ["Rent", "#1E5288"], ["Living costs", "#378DBD"], ["Loans & other", "#81D3EB"]];
  return (
    <Card title="Where each month's paycheck goes" subtitle="Gross monthly pay, split into taxes, savings, rent, living costs, loans — and what's left over.">
      <div className="h-[260px] w-full" role="img" aria-label="Stacked bar chart of monthly pay by category for each offer">
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <CartesianGrid horizontal={false} stroke="#E5E7EB" />
            <XAxis type="number" tickFormatter={(v) => usd(v)} fontSize={12} stroke="#6B7280" />
            <YAxis type="category" dataKey="name" width={110} fontSize={11} stroke="#374151" />
            <Tooltip formatter={(v: number) => usd(v)} cursor={{ fill: "rgba(16,106,177,0.06)" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {segs.map(([k, c]) => <Bar key={k} dataKey={k} stackId="a" fill={c} isAnimationActive={false} />)}
            <Bar dataKey="Left over" stackId="a" fill="#0C234B" radius={[0, 6, 6, 0]} isAnimationActive={false}>
              {data.map((d) => <Cell key={d.id} fill={OFFER_COLORS[d.id as OfferId]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {data.some((d) => d.short < 0) && (
        <p className="mt-2"><Status state="warn" label={data.filter((d) => d.short < 0).map((d) => `${d.name}: ${usd(d.short)}/mo short`).join(" · ")} /></p>
      )}
    </Card>
  );
}

function OfferCards({ rows, winner, result }: { rows: Row[]; winner: OfferId | null; result: PipelineResult }) {
  return (
    <div className={`grid gap-4 ${rows.length === 3 ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
      {rows.map((r) => {
        const culture = result.market?.results.find((m) => m.offer_id === r.offer_id)?.culture;
        return (
          <div key={r.offer_id} className={`card p-5 ${winner === r.offer_id ? "ring-2" : ""}`} style={{ borderTop: `5px solid ${OFFER_COLORS[r.offer_id]}`, ...(winner === r.offer_id ? { ["--tw-ring-color" as string]: OFFER_COLORS[r.offer_id] } : {}) }}>
            <div className="flex items-center justify-between">
              <OfferTag id={r.offer_id} label={r.label} />
              <span className="text-xs font-bold text-gray-500">#{r.rank} · {r.total_score?.toFixed(0) ?? "—"}/100</span>
            </div>
            <h3 className="mt-2 font-bold text-navy">{r.company}</h3>
            <p className="text-sm text-gray-600">{r.job_title} · {r.metro_name}</p>
            <p className="mt-4 text-xs font-semibold uppercase text-gray-500">Left over each month</p>
            <p className={`text-3xl font-extrabold tabular-nums ${r.left_over_monthly !== null && r.left_over_monthly < 0 ? "text-brandred" : "text-navy"}`}>{usd(r.left_over_monthly)}</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-gray-500">Base salary</dt><dd className="text-right font-semibold tabular-nums">{usd(r.base_salary)}</dd>
              <dt className="text-gray-500">Take-home / mo</dt><dd className="text-right font-semibold tabular-nums">{usd(r.take_home_monthly)}</dd>
              <dt className="text-gray-500">Year-1 total comp</dt><dd className="text-right font-semibold tabular-nums">{usd(r.comp_1yr)}</dd>
              <dt className="text-gray-500">3-year total comp</dt><dd className="text-right font-semibold tabular-nums">{usd(r.comp_3yr)}</dd>
              <dt className="text-gray-500">Local pay rank</dt><dd className="text-right font-semibold">{r.market_percentile !== null ? `~${ordinal(r.market_percentile)} pct` : "—"}</dd>
              <dt className="text-gray-500">Lifestyle fit</dt><dd className="text-right font-semibold">{r.lifestyle_score !== null ? `${r.lifestyle_score.toFixed(0)}/100` : "—"}</dd>
              <dt className="text-gray-500">Culture</dt><dd className="text-right font-semibold">{r.culture_rating !== null ? `${r.culture_rating.toFixed(1)}/5` : "—"}</dd>
            </dl>
            {culture?.source === "simulated" && <div className="mt-2 text-right"><SimulatedBadge text="SIMULATED reviews" /></div>}
            {r.missing.length > 0 && <p className="mt-3"><Status state="info" label={`Missing: ${r.missing.join(", ")}`} /></p>}
          </div>
        );
      })}
    </div>
  );
}

function Scorecard({ rows }: { rows: Row[] }) {
  const comps = rows[0]?.components ?? [];
  return (
    <Card title="Weighted scorecard" subtitle="Each component is scored 0–100, then weighted by your priorities. Change weights in What-if.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
              <th className="py-2 pr-3">Component</th><th className="py-2 pr-3">Weight</th>
              {rows.map((r) => <th key={r.offer_id} className="py-2 pr-3"><span className="inline-flex items-center gap-1.5"><OfferDot id={r.offer_id} />{r.label}</span></th>)}
            </tr>
          </thead>
          <tbody>
            {comps.map((c) => (
              <tr key={c.key} className="border-b border-gray-100 align-top">
                <td className="py-3 pr-3 font-medium text-gray-800">{c.label}{c.key === "culture" && <div className="mt-1"><SimulatedBadge /></div>}</td>
                <td className="py-3 pr-3 tabular-nums text-gray-600">{Math.round(c.weight * 100)}%</td>
                {rows.map((r) => {
                  const rc = r.components.find((x) => x.key === c.key);
                  return (
                    <td key={r.offer_id} className="py-3 pr-3">
                      <div className="flex items-center gap-2"><span className="w-8 font-semibold tabular-nums">{rc?.score.toFixed(0)}</span><ScoreBar value={rc?.score ?? null} color={OFFER_COLORS[r.offer_id]} /></div>
                      <p className="mt-1 text-xs text-gray-500">{rc?.basis}</p>
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td className="py-3 pr-3 font-bold text-navy">Total</td><td />
              {rows.map((r) => <td key={r.offer_id} className="py-3 pr-3 text-lg font-extrabold tabular-nums" style={{ color: OFFER_COLORS[r.offer_id] }}>{r.total_score?.toFixed(1)}</td>)}
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function WhatIf({ profile, base, set, reset, active, err }: { profile: Profile; base: Profile; set: (p: Partial<Profile>) => void; reset: () => void; active: boolean; err: string | null }) {
  const w = profile.weights;
  const weightKeys = useMemo(() => [["money_left_over", "Money left over"], ["total_comp", "Total comp"], ["lifestyle", "Lifestyle"], ["market_position", "Market position"], ["culture", "Culture"]] as const, []);
  return (
    <Card title="What-if" subtitle="Instant, deterministic recalculation — no AI involved." right={active ? <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={reset}><RotateCcw className="h-3.5 w-3.5" /> Reset</button> : undefined}>
      <div className="space-y-4">
        <div className="flex gap-2">
          {(["alone", "roommates"] as const).map((h) => (
            <button key={h} className={`btn flex-1 border px-2 py-1.5 text-xs ${profile.housing === h ? "border-navy bg-navy text-white" : "border-gray-300 bg-white text-navy"}`} onClick={() => set({ housing: h })}>
              {h === "alone" ? "Live alone" : "Roommate"}
            </button>
          ))}
        </div>
        <Slider label="Rents everywhere" value={profile.rent_adjust_pct} min={-30} max={50} step={5} suffix="%" onChange={(v) => set({ rent_adjust_pct: v })} />
        <Slider label="Bonus actually paid" value={profile.bonus_payout_pct} min={0} max={150} step={10} suffix="% of target" onChange={(v) => set({ bonus_payout_pct: v })} />
        <Slider label="401(k) contribution" value={profile.contribution_401k_pct} min={0} max={20} suffix="%" onChange={(v) => set({ contribution_401k_pct: v })} />
        <Slider label="Student loans" value={profile.student_loan_monthly} min={0} max={1500} step={25} suffix=" $/mo" onChange={(v) => set({ student_loan_monthly: v })} />
        <Slider label="Annual raise" value={profile.annual_raise_pct} min={0} max={10} step={0.5} suffix="%" onChange={(v) => set({ annual_raise_pct: v })} />
        <div className="border-t border-gray-100 pt-3">
          <p className="label">Scorecard weights</p>
          <div className="space-y-2">
            {weightKeys.map(([k, l]) => <Slider key={k} label={l} value={w[k]} min={0} max={60} step={5} onChange={(v) => set({ weights: { ...w, [k]: v } })} />)}
          </div>
        </div>
        {active && <p className="text-xs text-gray-500">Original settings: {base.housing === "alone" ? "living alone" : "with roommates"}, {base.contribution_401k_pct}% 401(k), {usd(base.student_loan_monthly)}/mo loans.</p>}
        {err && <p><AlertTriangle className="inline h-4 w-4 text-brandred" /> <span className="text-xs text-brandred">{err}</span></p>}
      </div>
    </Card>
  );
}
