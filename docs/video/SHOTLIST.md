# PriceMonkey video: shot list

Goes with `docs/video/SCRIPT.md`. Shot IDs (S2a, S3...) match the script beats.

## Setup before recording

- Server: `.venv/bin/uvicorn agora.api:app --port 8765` (README). Open **http://localhost:8765**.
- **Record from the replays, not live.** Live search stays off (it is off by default in the lab panel). The
  Sony A7 III numbers in the script come from `tests/fixtures/live_sony-a7-iii-body.jsonl`, which the
  `sony a7 iii body` query replays at no credit cost.
- Browser: a clean Chrome profile or window, 1920×1080, zoom 100%, no extensions or bookmarks bar visible, no
  other tabs. Hide the macOS dock and notifications (Do Not Disturb).
- Recorder: QuickTime (File → New Screen Recording) or OBS at 1080p60. Cursor visible but not huge.
- Turn **off** "Reduce motion" in macOS so the line animates (the app respects `prefers-reduced-motion`).
- Record every shot **2 or 3 times**, with 2 s of still screen before and after. Speed it up in the edit if
  needed, never slow it down.
- Record the host's voice-over separately with a close mic (phone voice memo next to the mouth is fine), then
  lay it over the cuts.

## Screen recordings

| ID | Beat | URL / action | What must be visible | Length to capture |
|---|---|---|---|---|
| S2a | 2 | `http://localhost:8765/?q=sony%20a7%20iii%20body` → wait for the hunt to finish → tap the **allenscamera.net** cutout (lowest tag) to open its receipt | Receipt rows: tag **$699.95 → €633.32** (USD at today's rate), **import VAT 25.5% €161.50**, **all in €794.82**. Zoom in on these three rows in the edit. | 8 s |
| S2b | 2 | Same receipt, scroll to the shipping line / flags | `outside the EU (USD): import VAT added, shipping to Finland unconfirmed` | 4 s |
| S2c | 2 | Same hunt → tap the **€239 mpb.com** "Sony Alpha A7 III" (pinned or in the "not counted" group) | Its flags: `too good to be true: 75% under the used median (€949)` and `price disagrees ... probably another item's price on the page`. It sits outside the counted offers. | 5 s |
| S3a | 3 | `http://localhost:8765/` start screen | The monkey and the example chips (`Sony A7 III body, used, under €900`, `iPhone 15, used, under €600`, `flat cleaning in Helsinki, 60 m²`...). Mouse goes to the search box. | 3 s |
| S3b | 3 | Press **/**, type `sony a7 iii body` at a natural speed, Enter | The banana loader (short), then offers flying onto the line from their shops, cheaper left, dearer right. | 10 s |
| S3c | 3 | Same hunt while it runs | The live log of every page read, plus the "Powered by Context.dev" banner if it's on screen. Zoom on 2 or 3 log rows. | 4 s |
| S4a | 4 | Same hunt after the last pages land | **The Turn**: the line switches from tag prices to all-in prices; the allenscamera.net cutout moves right. | 6 s |
| S4b | 4 | Tap the **tori.fi** used offer | Receipt: **€825, all in, in Finland**; resale and per-month figure (**€9.16/mo**). | 6 s |
| S4c | 4 | Scroll to the verdict | Headline: "Buy used at tori.fi for €825: resell in 12 mo for ~€715, so it costs €9.16/mo. The cheapest sticker (€633 at allenscamera.net) lands at €795 with import costs and costs €20/mo." | 5 s |
| S5a | 5 | Same hunt → drag the **yellow "your price" tag** along the line | The tag moving, offers left of it highlighting. | 5 s |
| S5b | 5 | `http://localhost:8765/?stage=1` → let it run (or press **skip ›**) to beat **6/7** "PriceMonkey watches overnight" | The overnight buy caption and the bought offer. Add the corner label `auto-buy shown on our demo shop`. | 6 s |
| S5c | 5 | Same tour → beat **7/7** "Proof, not promises." | The hash-chained log catching the edited row. | 5 s |
| S5d (optional) | 5 | Terminal, large font: `.venv/bin/python -m agora demo-buy --tmp-db` (offline, temp database) | The sold-out lie detector line ("page says 'sold out' although its structured data says in stock"), the haggle and the capped buy. Only use the lines that print; don't retype them. | 6 s |
| S6a | 6 | Start or results page → scroll to the footer | `We may earn a fee, never a better spot.` | 3 s |
| S6b | 6 | Same hunt → press **A** | The agent view: the same offers as JSON with `all_in_eur`. | 4 s |
| S7 | 7 | `http://localhost:8765/` start screen, idle | The monkey and logo, for the end card background. | 5 s |

**Backup for the whole demo in one take:** `http://localhost:8765/?stage=1` plays search → line → the Turn →
your price → overnight → proof with its own captions (7 beats). Record it once in full as a safety net.

## Camera shots (host)

| ID | Beat | Line | Framing |
|---|---|---|---|
| H1 | 1 | "Hey everybody, how's it going?..." | Chest-up, off-centre, eye level, a real room behind. Rossman style: no ring-light glamour. |
| H2 | 2 | "Good job, internet." | Same framing, deadpan, a half-second pause before the cut. |
| H6 | 6 | "And the business? We may earn a fee, never a better spot." | Same framing, slightly closer. |
| H7 | 7 | "PriceMonkey. Ask the monkey. That's it for today..." | Same framing, then cut to S7 with the end card. |

## Edit notes

- Captions burned in for every spoken line, plus the callouts in the script.
- Zoom (Ken Burns) on numbers as they are read. That's the "receipts" look: the viewer reads the number as you
  say it.
- Music: none, or very quiet under Beats 3 to 5 only. No music under the host.
- Monkey: the mascot appears in S3a/S3b (loader) and on the end card. No other monkey effects or sounds.
- Export: 1920×1080, H.264, check the final file length is **≤ 1:58** before uploading.

---

## Guidebook checklist for the video and the submission

From `guidebook.txt` (Project Submission, Rules) and the Context.dev tech challenge text.

**The video**
- [ ] **No longer than 2:00.** "Not a second longer than 2 minutes, and we will be very strict with this."
      Check the exported file's length, not the timeline's.
- [ ] Uploaded to **YouTube or Vimeo** (or similar) and **public or unlisted, viewable by everyone**. Open the
      link in a private window to check.
- [ ] Shows the **final** project.
- [ ] Context.dev data **visibly drives something** in it (tech challenge minimum): S3c, S4a, S4c.

**The submission form (due Sun 15 Nov 10:00, the form closes automatically, no late entries)**
- [ ] Project name, punchline, description
- [ ] Challenge(s) selected (Context.dev main, plus Best Use of Context.dev)
- [ ] Technologies used
- [ ] Video link (above)
- [ ] Demo link and source code link; the repo is public (all submissions are MIT, organisers must be able to
      access the code)
- [ ] Note on **which Context.dev endpoints we used and why** (tech challenge "What to submit")
- [ ] Credit choice
- [ ] Pitch deck (PDF)
- [ ] Phone numbers of all team members, Discord username
- [ ] Project status switched from **DRAFT to FINAL** before 10:00 (drafts are not reviewed)
- [ ] Whole team attends the live **peer review** on Sunday (required for the main prize)
