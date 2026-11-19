import { useEffect, useRef, useState } from "react";
import { ArrowRight, FileText, Keyboard, Lock, Plus, Trash2, Upload, ClipboardPaste, Download } from "lucide-react";
import { getSamples } from "../api";
import type { ManualForm, OfferDraft, OfferId, Profile, Sample } from "../types";
import { Card, OfferDot, SimulatedBadge, Slider } from "./ui";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.eml,.md";

export function newDraft(id: OfferId): OfferDraft {
  return { offer_id: id, label: `Offer ${id}`, source: "file", file: null, text: "", form: {}, reviews: "" };
}

interface Props {
  profile: Profile;
  setProfile: (p: Profile) => void;
  offers: OfferDraft[];
  setOffers: (o: OfferDraft[]) => void;
  onCompare: () => void;
  onSample: (s: Sample) => void;
  error: string | null;
  busy: boolean;
}

export default function InputView({ profile, setProfile, offers, setOffers, onCompare, onSample, error, busy }: Props) {
  const [samples, setSamples] = useState<Sample[]>([]);
  useEffect(() => { getSamples().then(setSamples).catch(() => setSamples([])); }, []);

  const update = (i: number, patch: Partial<OfferDraft>) => setOffers(offers.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  const ready = offers.length >= 2 && offers.every((o) => (o.source === "file" ? !!o.file : o.source === "text" ? o.text.trim().length > 40 : !!(o.form.base_salary || o.form.hourly_rate) && !!o.form.office_city));

  return (
    <div className="space-y-8">
      <section className="rounded-3xl bg-navy px-6 py-10 text-white sm:px-10 sm:py-14">
        <p className="text-sm font-semibold uppercase tracking-widest text-sky">For college seniors & new grads</p>
        <h1 className="mt-3 max-w-3xl text-3xl font-extrabold leading-tight sm:text-5xl">The bigger salary isn't always the better offer.</h1>
        <p className="mt-4 max-w-2xl text-base text-navy-100 sm:text-lg">
          Upload 2–3 job offers in different cities. Six agents work out what each one is <em>really</em> worth after taxes, rent,
          living costs, benefits and the lifestyle you want — with every number traced to public data.
        </p>
        <div className="mt-6 flex flex-wrap gap-3 text-sm text-navy-100">
          <span className="inline-flex items-center gap-1.5"><Lock className="h-4 w-4" /> Offers are processed in memory and never stored</span>
          <span className="inline-flex items-center gap-1.5"><FileText className="h-4 w-4" /> PDF, image, Word or pasted text</span>
        </div>
      </section>

      {samples.length > 0 && (
        <Card title="Try a sample comparison" subtitle="Fictional offer letters with realistic numbers. One click runs all six agents." right={<SimulatedBadge text="SIMULATED samples" />}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {samples.map((s) => (
              <div key={s.id} className="flex flex-col rounded-xl border border-gray-200 p-4 hover:border-arroyo">
                <div className="flex items-center gap-1.5">{s.offers.map((o) => <OfferDot key={o.offer_id} id={o.offer_id} />)}</div>
                <h3 className="mt-2 font-semibold text-navy">{s.title}</h3>
                <p className="mt-1 flex-1 text-sm text-gray-600">{s.description}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button className="btn-primary px-3 py-1.5" disabled={busy} onClick={() => onSample(s)}>Compare <ArrowRight className="h-4 w-4" /></button>
                  {s.offers.map((o) => (
                    <a key={o.file} className="inline-flex items-center gap-1 text-xs text-arroyo hover:underline" href={`/api/samples/file/${o.file}`} download>
                      <Download className="h-3 w-3" />{o.offer_id} ({o.format})
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-4">
          <h2 className="section-title">Your offers</h2>
          {offers.map((o, i) => (
            <OfferCard key={o.offer_id} draft={o} onChange={(p) => update(i, p)} onRemove={offers.length > 2 ? () => setOffers(offers.filter((_, j) => j !== i)) : undefined} />
          ))}
          {offers.length < 3 && (
            <button className="btn-ghost w-full border-dashed" onClick={() => setOffers([...offers, newDraft((["A", "B", "C"] as OfferId[]).find((x) => !offers.some((o) => o.offer_id === x))!)])}>
              <Plus className="h-4 w-4" /> Add a third offer
            </button>
          )}
        </div>
        <ProfilePanel profile={profile} setProfile={setProfile} />
      </div>

      <div className="sticky bottom-4 z-10 flex flex-col items-center gap-2">
        {error && <p role="alert" className="rounded-lg bg-brandred-50 px-4 py-2 text-sm font-medium text-brandred">{error}</p>}
        <button className="btn-red px-8 py-3 text-base shadow-card" disabled={!ready || busy} onClick={onCompare}>
          Compare my offers <ArrowRight className="h-5 w-5" />
        </button>
        {!ready && <p className="text-xs text-gray-500">Add at least two offers: a file, pasted text, or salary + city in the form.</p>}
      </div>
    </div>
  );
}

function OfferCard({ draft, onChange, onRemove }: { draft: OfferDraft; onChange: (p: Partial<OfferDraft>) => void; onRemove?: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [showReviews, setShowReviews] = useState(false);
  const tabs = [
    { key: "file", label: "Upload", icon: <Upload className="h-4 w-4" /> },
    { key: "text", label: "Paste text", icon: <ClipboardPaste className="h-4 w-4" /> },
    { key: "form", label: "Type it in", icon: <Keyboard className="h-4 w-4" /> },
  ] as const;
  const setForm = (k: keyof ManualForm, v: string, num = true) =>
    onChange({ form: { ...draft.form, [k]: v === "" ? undefined : num ? Number(v) : v } });

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center gap-3 border-b border-gray-100 px-5 py-3" style={{ borderLeft: `6px solid var(--offer-${draft.offer_id.toLowerCase()})` }}>
        <OfferDot id={draft.offer_id} size={12} />
        <input className="w-40 bg-transparent text-base font-bold text-navy focus:outline-none" value={draft.label} maxLength={40}
          onChange={(e) => onChange({ label: e.target.value })} aria-label={`Name for offer ${draft.offer_id}`} />
        <div className="ml-auto flex rounded-lg bg-gray-100 p-0.5" role="tablist">
          {tabs.map((t) => (
            <button key={t.key} role="tab" aria-selected={draft.source === t.key} onClick={() => onChange({ source: t.key })}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold ${draft.source === t.key ? "bg-white text-navy shadow" : "text-gray-500"}`}>
              {t.icon}<span className="hidden sm:inline">{t.label}</span>
            </button>
          ))}
        </div>
        {onRemove && <button aria-label="Remove offer" className="text-gray-400 hover:text-brandred" onClick={onRemove}><Trash2 className="h-4 w-4" /></button>}
      </div>
      <div className="p-5">
        {draft.source === "file" && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) onChange({ file: f }); }}
            onClick={() => fileRef.current?.click()} role="button" tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${drag ? "border-arroyo bg-arroyo-50" : "border-gray-300 hover:border-arroyo"}`}>
            <Upload className="h-6 w-6 text-arroyo" />
            {draft.file ? (
              <p className="mt-2 text-sm font-semibold text-navy">{draft.file.name} <span className="font-normal text-gray-500">({Math.ceil(draft.file.size / 1024)} KB)</span></p>
            ) : (
              <p className="mt-2 text-sm text-gray-600"><span className="font-semibold text-navy">Drop your offer letter</span> or click to choose</p>
            )}
            <p className="mt-1 text-xs text-gray-500">PDF, PNG/JPG (read with offline OCR), DOCX or TXT · up to 10 MB</p>
            <input ref={fileRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => onChange({ file: e.target.files?.[0] ?? null })} />
          </div>
        )}
        {draft.source === "text" && (
          <textarea className="input h-44 font-mono text-xs" placeholder="Paste the offer email or letter here…" value={draft.text}
            onChange={(e) => onChange({ text: e.target.value })} maxLength={60000} aria-label="Offer text" />
        )}
        {draft.source === "form" && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <TextField label="Company" v={draft.form.company} on={(v) => setForm("company", v, false)} span />
            <TextField label="Job title" v={draft.form.job_title} on={(v) => setForm("job_title", v, false)} span />
            <TextField label="Office city" v={draft.form.office_city} on={(v) => setForm("office_city", v, false)} />
            <TextField label="State (2 letters)" v={draft.form.office_state} on={(v) => setForm("office_state", v.toUpperCase().slice(0, 2), false)} />
            <NumField label="Base salary ($/yr)" v={draft.form.base_salary} on={(v) => setForm("base_salary", v)} />
            <NumField label="Signing bonus ($)" v={draft.form.signing_bonus} on={(v) => setForm("signing_bonus", v)} />
            <NumField label="Bonus target (% of base)" v={draft.form.bonus_target_pct} on={(v) => setForm("bonus_target_pct", v)} />
            <NumField label="PTO days" v={draft.form.pto_days} on={(v) => setForm("pto_days", v)} />
            <NumField label="401(k) match rate (%)" v={draft.form.match_rate_pct} on={(v) => setForm("match_rate_pct", v)} hint="100 = dollar-for-dollar" />
            <NumField label="…on first (% of pay)" v={draft.form.match_up_to_pct} on={(v) => setForm("match_up_to_pct", v)} />
            <NumField label="Relocation ($)" v={draft.form.relocation} on={(v) => setForm("relocation", v)} />
            <NumField label="Employer HSA ($/yr)" v={draft.form.hsa_employer_annual} on={(v) => setForm("hsa_employer_annual", v)} />
            <NumField label="Equity value ($)" v={draft.form.equity_value_usd} on={(v) => setForm("equity_value_usd", v)} />
            <NumField label="Vesting years" v={draft.form.equity_vesting_years} on={(v) => setForm("equity_vesting_years", v)} />
            <label className="col-span-2 block">
              <span className="label">Work arrangement</span>
              <select className="input" value={draft.form.work_arrangement ?? ""} onChange={(e) => setForm("work_arrangement", e.target.value, false)}>
                <option value="">not stated</option><option value="onsite">On-site</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option>
              </select>
            </label>
          </div>
        )}
        <button className="mt-3 text-xs font-semibold text-arroyo hover:underline" onClick={() => setShowReviews(!showReviews)}>
          {showReviews ? "Hide" : "Optional: paste employee reviews for this company"}
        </button>
        {showReviews && (
          <textarea className="input mt-2 h-24 text-xs" placeholder="Paste a few reviews (they stay in memory only)…" value={draft.reviews}
            onChange={(e) => onChange({ reviews: e.target.value })} maxLength={20000} aria-label="Employee reviews" />
        )}
      </div>
    </div>
  );
}

function TextField({ label, v, on, span }: { label: string; v?: string; on: (v: string) => void; span?: boolean }) {
  return (
    <label className={`block ${span ? "col-span-2" : ""}`}>
      <span className="label">{label}</span>
      <input className="input" value={v ?? ""} onChange={(e) => on(e.target.value)} maxLength={120} />
    </label>
  );
}
function NumField({ label, v, on, hint }: { label: string; v?: number; on: (v: string) => void; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input className="input" type="number" min={0} inputMode="decimal" value={v ?? ""} onChange={(e) => on(e.target.value)} />
      {hint && <span className="text-[11px] text-gray-500">{hint}</span>}
    </label>
  );
}

const PRIORITY_LABELS: [keyof Profile["priorities"], string][] = [
  ["outdoors", "Outdoors & nature"], ["nightlife", "Nightlife & young crowd"], ["weather", "Nice weather"],
  ["commute", "Short commute"], ["family", "Close to family"], ["cost_of_fun", "Cheap fun"],
];

function ProfilePanel({ profile, setProfile }: { profile: Profile; setProfile: (p: Profile) => void }) {
  const set = (patch: Partial<Profile>) => setProfile({ ...profile, ...patch });
  return (
    <aside className="min-w-0 space-y-4">
      <h2 className="section-title">About you</h2>
      <Card>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><span className="label">Student loans ($/mo)</span>
              <input className="input" type="number" min={0} value={profile.student_loan_monthly} onChange={(e) => set({ student_loan_monthly: Math.max(0, Number(e.target.value)) })} /></label>
            <label className="block"><span className="label">Other fixed costs ($/mo)</span>
              <input className="input" type="number" min={0} value={profile.extras_monthly} onChange={(e) => set({ extras_monthly: Math.max(0, Number(e.target.value)) })} /></label>
          </div>
          <div>
            <span className="label">Housing</span>
            <div className="flex gap-2">
              {(["alone", "roommates"] as const).map((h) => (
                <button key={h} className={`btn flex-1 border ${profile.housing === h ? "border-navy bg-navy text-white" : "border-gray-300 bg-white text-navy"}`} onClick={() => set({ housing: h })}>
                  {h === "alone" ? "Live alone" : "With roommates"}
                </button>
              ))}
            </div>
            {profile.housing === "roommates" && (
              <select className="input mt-2" value={profile.roommates} onChange={(e) => set({ roommates: Number(e.target.value) })} aria-label="Number of roommates">
                {[1, 2, 3].map((n) => <option key={n} value={n}>{n} roommate{n > 1 ? "s" : ""}</option>)}
              </select>
            )}
          </div>
          <Slider label="Your 401(k) contribution" value={profile.contribution_401k_pct} min={0} max={20} step={1} suffix="%" onChange={(v) => set({ contribution_401k_pct: v })} />
          <label className="block"><span className="label">Home city (for distance to family)</span>
            <input className="input" placeholder="e.g. Tucson, AZ" value={profile.home_city ?? ""} onChange={(e) => set({ home_city: e.target.value || null })} maxLength={80} /></label>
          <label className="block"><span className="label">Where you'd live if an offer is remote</span>
            <input className="input" placeholder="e.g. Denver, CO" value={profile.remote_city ?? ""} onChange={(e) => set({ remote_city: e.target.value || null })} maxLength={80} /></label>
          <label className="block"><span className="label">Health premium ($/mo, optional)</span>
            <input className="input" type="number" min={0} placeholder="blank = national average ($120)" value={profile.health_premium_monthly ?? ""}
              onChange={(e) => set({ health_premium_monthly: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) })} /></label>
        </div>
      </Card>
      <Card title="What matters to you" subtitle="0 = don't care · 5 = very important">
        <div className="space-y-3">
          {PRIORITY_LABELS.map(([k, l]) => (
            <Slider key={k} label={l} value={profile.priorities[k]} min={0} max={5} onChange={(v) => set({ priorities: { ...profile.priorities, [k]: v } })} />
          ))}
        </div>
      </Card>
    </aside>
  );
}
