# Demo video script (2:45)

The assignment asks for a 2–3 minute screen recording that shows **the input, the agent pipeline processing, and the
output**, and explains **why each agent exists**.

**Before recording:** start TrueOffer (double-click `Start TrueOffer.command`), open it in a full-screen browser
window, and turn on Do Not Disturb. On a Mac, press **Shift-Command-5 → Record Entire Screen** and check
**Options → Microphone**. Practice once; aim for 2:30–2:50.

---

### 0:00–0:20 · The problem (home page)
> "New grads compare job offers by salary. But a bigger salary in an expensive city can leave you with *less*
> money. TrueOffer is a multi-agent AI product that shows what each offer is really worth after taxes, rent,
> living costs, benefits and lifestyle."

*Scroll slowly past the hero and the sample cards.*

### 0:20–0:45 · The input
> "I can upload offer letters as PDFs, phone photos or Word files, or just paste the email. I'll use a sample:
> a $95,000 finance offer in New York versus $87,000 in Charlotte. The Charlotte offer is a scanned image."

*Briefly show the "About you" panel (student loans, live alone vs. roommates, priority sliders).*
> "I also tell it about me: my student loans, whether I'll have roommates, and what I care about in a city."

*Click **Compare** on "Finance: New York vs. Charlotte."*

### 0:45–1:20 · The agent pipeline (progress screen)
> "Six specialized agents run in three stages, coordinated by an orchestrator.
> First, one **Offer Parser** per offer reads the letter, using offline OCR for the photo, and pulls out every
> field with a quote as evidence. If something isn't in the letter, it says 'not stated' instead of guessing.
> Then four agents run in parallel, because none of them depends on the others: **Tax** works out 2026 federal,
> state and city taxes; **Cost of Living** prices rent and everyday costs from Zillow, Census and BLS data;
> **Market** checks where the salary falls in BLS wage data for that job and city; **Lifestyle** scores the
> city on what I said matters to me.
> Finally the **Decision Strategist** combines everything."

*(The run is fast. If it finishes mid-sentence, keep narrating over the results, or scroll to **Under the hood**,
which shows each agent's time and confidence.)*

### 1:20–2:10 · The output
> "Here's the answer. Even though New York pays $8,000 more, **Charlotte leaves me about $1,800 more every month**.
> New York actually leaves me $182 short after city tax and Manhattan rent."

*Point at the paycheck chart, then the offer cards.*
> "This chart shows where each paycheck goes: taxes, savings, rent, living costs, and what's left."

*Scroll to the scorecard, then the What-if panel. Drag **Rents everywhere** or switch to **Roommate**.*
> "The scorecard weighs money, total comp, lifestyle, market pay and culture by my priorities. With what-if
> sliders I can change assumptions and it recalculates instantly. And it tells me what would flip the decision."

*Open **Details → Taxes** (New York) for a second.*
> "Every number shows its formula and its public source."

### 2:10–2:35 · Acting on it
*Scroll to the negotiation email and recruiter questions.*
> "It also drafts a negotiation email backed by BLS wage data, and lists questions to ask each recruiter based on
> what the letter left out. I review and send it myself; nothing is sent automatically."

### 2:35–2:50 · Why it's trustworthy
> "All the money math is deterministic code over public data: taxes match an independent worksheet to the
> cent, and the parser got 195 out of 195 fields right on our test letters. Offers are processed in memory and
> never stored. That's TrueOffer: the bigger salary isn't always the better offer."

---

**Backup:** if anything goes wrong live, show the screenshots in `docs/screenshots/`, or run
`.venv/bin/python -m backend.tests.run_pipeline_eval` in Terminal to show all six comparisons.
