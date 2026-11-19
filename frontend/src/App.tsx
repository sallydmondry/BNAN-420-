import { useEffect, useRef, useState } from "react";
import { followRun, getSamples, startCompare } from "./api";
import InputView, { newDraft } from "./components/InputView";
import ProgressView from "./components/ProgressView";
import ResultsView from "./components/ResultsView";
import { DEFAULT_PROFILE, type OfferDraft, type PipelineResult, type Profile, type ProgressEvent, type Sample } from "./types";

type View = "input" | "running" | "results";

export default function App() {
  const [view, setView] = useState<View>("input");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const [offers, setOffers] = useState<OfferDraft[]>([newDraft("A"), newDraft("B")]);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => () => stop.current?.(), []);
  // Deep link for demos: /?sample=<sample-id> runs that SIMULATED sample immediately.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("sample");
    if (!id) return;
    getSamples().then((all) => { const s = all.find((x) => x.id === id); if (s) runSample(s); }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "smooth" }); }, [view]);

  const run = async (p: Profile, sampleId?: string) => {
    setError(null);
    setEvents([]);
    setResult(null);
    setView("running");
    try {
      const id = await startCompare(p, offers, sampleId);
      stop.current = followRun(
        id,
        (e) => setEvents((prev) => [...prev, e]),
        (r) => { setResult(r); setView("results"); },
        (m) => { setError(m); setView("input"); },
      );
    } catch (e) {
      setError((e as Error).message);
      setView("input");
    }
  };

  const runSample = (s: Sample) => {
    const p: Profile = { ...DEFAULT_PROFILE, ...s.profile, priorities: { ...DEFAULT_PROFILE.priorities, ...(s.profile.priorities ?? {}) }, weights: { ...DEFAULT_PROFILE.weights, ...(s.profile.weights ?? {}) } };
    setProfile(p);
    run(p, s.id);
  };

  return (
    <div className="min-h-screen overflow-x-clip">
      <header className="no-print border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <button className="flex items-center gap-2" onClick={() => { stop.current?.(); setView("input"); }} aria-label="TrueOffer home">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <span className="text-lg font-extrabold tracking-tight text-navy">True<span className="text-brandred">Offer</span></span>
          </button>
          <span className="hidden text-sm text-gray-500 sm:block">What your job offer is really worth</span>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-10">
        {view === "input" && <InputView profile={profile} setProfile={setProfile} offers={offers} setOffers={setOffers} onCompare={() => run(profile)} onSample={runSample} error={error} busy={false} />}
        {view === "running" && <ProgressView events={events} />}
        {view === "results" && result && <ResultsView result={result} onRestart={() => setView("input")} />}
      </main>
      <footer className="border-t border-gray-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 text-xs text-gray-500 sm:px-6">
          TrueOffer · BNAN 420 final project. Estimates for comparison only — not tax, legal or financial advice. Sample companies and reviews are SIMULATED.
        </div>
      </footer>
    </div>
  );
}
