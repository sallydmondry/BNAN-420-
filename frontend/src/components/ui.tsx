import { AlertTriangle, CheckCircle2, Circle, CircleSlash, FlaskConical, Info, Loader2, Cpu, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { OFFER_COLORS, type Extracted, type OfferId } from "../types";
import { NOT_STATED } from "../format";

/** Status is always icon + label + color (brand palette only). */
export function Status({ state, label }: { state: "waiting" | "running" | "done" | "failed" | "skipped" | "warn" | "info"; label?: string }) {
  const map = {
    waiting: { icon: <Circle className="h-4 w-4" />, cls: "text-gray-400", text: "Waiting" },
    running: { icon: <Loader2 className="h-4 w-4 animate-spin" />, cls: "text-arroyo", text: "Running" },
    done: { icon: <CheckCircle2 className="h-4 w-4" />, cls: "text-navy", text: "Done" },
    failed: { icon: <AlertTriangle className="h-4 w-4" />, cls: "text-brandred", text: "Failed" },
    skipped: { icon: <CircleSlash className="h-4 w-4" />, cls: "text-gray-500", text: "Skipped" },
    warn: { icon: <AlertTriangle className="h-4 w-4" />, cls: "text-brandred", text: "Check" },
    info: { icon: <Info className="h-4 w-4" />, cls: "text-arroyo", text: "Note" },
  }[state];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${map.cls}`}>
      {map.icon}
      {label ?? map.text}
    </span>
  );
}

export function OfferDot({ id, size = 10 }: { id: OfferId; size?: number }) {
  return <span aria-hidden className="inline-block rounded-full shrink-0" style={{ width: size, height: size, background: OFFER_COLORS[id] }} />;
}

export function OfferTag({ id, label }: { id: OfferId; label?: string }) {
  return (
    <span className="chip text-white" style={{ background: OFFER_COLORS[id] }}>
      {label ?? `Offer ${id}`}
    </span>
  );
}

export function SimulatedBadge({ text = "SIMULATED" }: { text?: string }) {
  return (
    <span className="chip border border-dashed border-gray-400 bg-gray-100 text-gray-700" title="Simulated data: fictional, for demonstration only">
      <FlaskConical className="h-3 w-3" /> {text}
    </span>
  );
}

export function EngineBadge({ engine }: { engine: string }) {
  return engine === "claude" ? (
    <span className="chip bg-arroyo-50 text-arroyo"><Sparkles className="h-3 w-3" /> Claude</span>
  ) : (
    <span className="chip bg-navy-50 text-navy"><Cpu className="h-3 w-3" /> Local engine</span>
  );
}

export function Card({ title, subtitle, right, children, className = "" }: { title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-5 sm:p-6 ${className}`}>
      {(title || right) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="section-title">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-gray-500">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/** Renders an extracted field, showing the canonical "not stated in offer" label when missing. */
export function FieldValue<T>({ f, fmt }: { f: Extracted<T>; fmt?: (v: T) => string }) {
  if (f.value === null || f.status === "not_stated") {
    return <span className="italic text-gray-400">{NOT_STATED}</span>;
  }
  return <span>{fmt ? fmt(f.value as T) : String(f.value)}</span>;
}

export function ScoreBar({ value, color = "#106AB1", max = 100 }: { value: number | null; color?: string; max?: number }) {
  const w = value === null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-2 w-full rounded-full bg-gray-100" role="meter" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={max}>
      <div className="h-2 rounded-full transition-all" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

export function Slider({ label, value, min, max, step = 1, onChange, suffix = "", hint }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; suffix?: string; hint?: string }) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <span className="text-sm font-semibold tabular-nums text-navy">{value}{suffix}</span>
      </div>
      <input type="range" className="mt-1 w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
      {hint && <span className="text-xs text-gray-500">{hint}</span>}
    </label>
  );
}
