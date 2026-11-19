import type { OfferDraft, PipelineResult, Profile, ProgressEvent, RecalcContext, RecalcResponse, Sample } from "./types";

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try { const j = await r.json(); if (j?.detail) msg = typeof j.detail === "string" ? j.detail : msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const getSamples = () => fetch("/api/samples").then((r) => asJson<Sample[]>(r));
export const getHealth = () => fetch("/api/health").then((r) => asJson<{ engine: string; data_built: string }>(r));

/** Start a comparison. Files go as multipart parts; everything else in a JSON `payload` part. */
export async function startCompare(profile: Profile, offers: OfferDraft[], sampleId?: string): Promise<string> {
  const fd = new FormData();
  const payload = sampleId
    ? { sample_id: sampleId, profile }
    : {
        profile,
        offers: offers.map((o) => ({
          offer_id: o.offer_id, label: o.label, source: o.source,
          text: o.source === "text" ? o.text : undefined,
          // For uploads/pastes, the form carries optional user corrections ("Add or correct details").
          form: o.source === "form" || Object.keys(cleanForm(o.form)).length ? cleanForm(o.form) : undefined,
          pasted_reviews: o.reviews.trim() || undefined,
        })),
      };
  fd.append("payload", JSON.stringify(payload));
  if (!sampleId) for (const o of offers) if (o.source === "file" && o.file) fd.append(`file_${o.offer_id}`, o.file, o.file.name);
  const r = await fetch("/api/compare", { method: "POST", body: fd });
  return (await asJson<{ run_id: string }>(r)).run_id;
}

function cleanForm(f: object) {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(f)) if (v !== "" && v !== undefined && v !== null && !(typeof v === "number" && isNaN(v))) out[k] = v;
  return out;
}

/** Follow a run over SSE; falls back to polling if EventSource fails. */
export function followRun(runId: string, onEvent: (e: ProgressEvent) => void, onResult: (r: PipelineResult) => void, onError: (m: string) => void): () => void {
  let closed = false;
  const es = new EventSource(`/api/compare/${runId}/events`);
  es.addEventListener("progress", (m) => onEvent(JSON.parse((m as MessageEvent).data)));
  es.addEventListener("result", (m) => { closed = true; es.close(); onResult(JSON.parse((m as MessageEvent).data)); });
  es.addEventListener("failed", (m) => { closed = true; es.close(); onError(JSON.parse((m as MessageEvent).data).error || "Run failed"); });
  es.onerror = () => {
    if (closed) return;
    es.close();
    const poll = async () => {
      if (closed) return;
      try {
        const r = await fetch(`/api/compare/${runId}/result`);
        if (r.status === 202) { setTimeout(poll, 800); return; }
        closed = true;
        onResult(await asJson<PipelineResult>(r));
      } catch (e) { closed = true; onError((e as Error).message); }
    };
    poll();
  };
  return () => { closed = true; es.close(); };
}

export const recalculate = (context: RecalcContext, overrides: Record<string, unknown>) =>
  fetch("/api/recalculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ context, overrides }) })
    .then((r) => asJson<RecalcResponse>(r));
