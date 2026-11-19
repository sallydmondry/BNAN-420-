import { motion } from "framer-motion";
import { Building2, Calculator, FileSearch, Home, Scale, Sun } from "lucide-react";
import type { OfferId, ProgressEvent } from "../types";
import { OfferDot, Status } from "./ui";

const AGENTS = [
  { key: "offer_parser", n: 1, name: "Offer Parser", what: "Reads each letter (PDF text or offline OCR) and pulls out the fields. Anything missing is marked “not stated in offer.”", icon: FileSearch, stage: 1 },
  { key: "tax", n: 2, name: "Tax & Take-Home", what: "2026 federal, Social Security, Medicare, state and city taxes.", icon: Calculator, stage: 2 },
  { key: "cost_of_living", n: 3, name: "Cost of Living & Housing", what: "Market rent (Zillow + Census) and living costs (BLS × BEA prices).", icon: Home, stage: 2 },
  { key: "market", n: 4, name: "Market & Company", what: "Where your pay sits in BLS wage data, plus culture signals.", icon: Building2, stage: 2 },
  { key: "lifestyle", n: 5, name: "Lifestyle Fit", what: "Weather, commute, outdoors, nightlife and distance to family vs. your priorities.", icon: Sun, stage: 2 },
  { key: "decision", n: 6, name: "Decision Strategist", what: "Money left over, the weighted scorecard, what-ifs, and a negotiation email.", icon: Scale, stage: 3 },
];

type St = "waiting" | "running" | "done" | "failed";

export function agentStates(events: ProgressEvent[]) {
  const st: Record<string, { state: St; summary: string; ms: number | null; perOffer: Record<string, St> }> = {};
  for (const a of AGENTS) st[a.key] = { state: "waiting", summary: "", ms: null, perOffer: {} };
  for (const e of events) {
    if (!e.agent || !st[e.agent]) continue;
    const s = st[e.agent];
    const next: St = e.type === "agent_started" ? "running" : e.type === "agent_finished" ? "done" : e.type === "agent_failed" ? "failed" : s.state;
    if (e.offer_id) {
      s.perOffer[e.offer_id] = next;
      const vals = Object.values(s.perOffer);
      s.state = vals.includes("running") ? "running" : vals.includes("failed") ? "failed" : "done";
      if (e.type !== "agent_started") s.summary = e.summary;
    } else {
      s.state = next;
      if (e.type !== "agent_started") s.summary = e.summary;
    }
    if (e.elapsed_ms !== null && e.elapsed_ms !== undefined) s.ms = Math.max(s.ms ?? 0, e.elapsed_ms);
  }
  return st;
}

export default function ProgressView({ events }: { events: ProgressEvent[] }) {
  const st = agentStates(events);
  const started = events.find((e) => e.type === "pipeline_started");
  const offers = (started?.data?.offers as OfferId[] | undefined) ?? [];
  const stages = [
    { n: 1, title: "Stage 1 · Read the offers", note: "one parser per offer, in parallel" },
    { n: 2, title: "Stage 2 · Analyze", note: "four independent agents, in parallel" },
    { n: 3, title: "Stage 3 · Decide", note: "combines everything" },
  ];
  return (
    <div className="mx-auto max-w-3xl">
      <div className="text-center">
        <h1 className="text-2xl font-extrabold text-navy sm:text-3xl">Six agents are working on your offers</h1>
        <p className="mt-2 text-gray-600">This usually takes a few seconds. Nothing you upload is saved.</p>
        {offers.length > 0 && <div className="mt-3 flex justify-center gap-2">{offers.map((o) => <span key={o} className="inline-flex items-center gap-1 text-sm text-gray-600"><OfferDot id={o} /> Offer {o}</span>)}</div>}
      </div>
      <div className="mt-8 space-y-6">
        {stages.map((stg) => (
          <div key={stg.n}>
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-500">{stg.title} <span className="font-normal normal-case tracking-normal">— {stg.note}</span></p>
            <div className={`grid gap-3 ${stg.n === 2 ? "sm:grid-cols-2" : ""}`}>
              {AGENTS.filter((a) => a.stage === stg.n).map((a) => {
                const s = st[a.key];
                const Icon = a.icon;
                return (
                  <motion.div key={a.key} layout className={`card flex gap-3 p-4 ${s.state === "running" ? "ring-2 ring-arroyo/40" : ""}`}>
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${s.state === "done" ? "bg-navy text-white" : s.state === "failed" ? "bg-brandred-50 text-brandred" : "bg-gray-100 text-gray-500"}`}>
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold text-navy">{a.n}. {a.name}</p>
                        <Status state={s.state} label={s.state === "done" && s.ms !== null ? `Done · ${s.ms} ms` : undefined} />
                      </div>
                      <p className="mt-0.5 text-sm text-gray-600">{s.summary || a.what}</p>
                      {a.key === "offer_parser" && Object.keys(s.perOffer).length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-3">
                          {Object.entries(s.perOffer).map(([o, v]) => <span key={o} className="inline-flex items-center gap-1 text-xs"><OfferDot id={o as OfferId} /><Status state={v} label={`Offer ${o}`} /></span>)}
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
