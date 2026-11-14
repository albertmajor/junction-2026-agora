# Dev type panel

A local-only panel for trying fonts and type settings on the real page, exporting them as JSON, and
writing that JSON into the code in one step.

- Code: `agora/web/js/devtools.js`, `agora/web/css/devtools.css`. `main.js` imports them through one
  line, and only when `location.hostname` is `localhost`, `127.0.0.1` or `[::1]`. Visitors on any other
  host never download them.
- Apply script: `scripts/apply_fonts.py`
- Tests: `tests/test_devtools_fonts.py`, which runs `tests/web/devtools.test.mjs` in node.

## Open it

Run the site locally, for example `.venv/bin/uvicorn agora.api:app --port 8765`. Then do one of these:

- open `http://localhost:8765/?dev=1`
- press **Ctrl+Shift+D** or **Cmd+Shift+D** to toggle the panel

To move the panel, drag its header. **–** collapses it and **×** closes it. When you close the panel
while custom settings are active, a small "Aa custom type" pill appears in the bottom right; click it to
reopen the panel. Your settings and the panel's position stay in `localStorage`, so a reload keeps them.

## What you can set

The page uses three type roles:

| Role | Token | What uses it now |
|---|---|---|
| **Main**, the UI sans (the main one) | `--sans` | body text, buttons, chips, labels (Instrument Sans) |
| **Display** | `--serif` | the start question, headlines, prices, the logo (Fraunces) |
| **Mono** | `--mono` | numbers in tables, the ticker, the live log (IBM Plex Mono) |

For each role you can set:

- **Font.** Pick from a curated list of 58 Google Fonts, grouped by style: grotesk sans close to
  Instrument Sans, geometric, humanist, serif and mono. Each name is shown in its own face. You can also
  type any Google Fonts family and press **Load**. The panel asks fonts.googleapis.com which weights
  exist and whether there is a variable `wght` axis. To add other axes, type them, e.g.
  `wdth 75..100, opsz 8..60`.
- **weight.** A slider for variable fonts, or a list for static ones. For static fonts, the checkboxes
  choose which weights are loaded.
- **Variation axes** other than `wght`, such as `opsz`, `wdth`, `SOFT` or `slnt`. These become
  `--sans-vs`, `--display-vs` and `--mono-vs`. **clear axes** sets them back to the font's own
  defaults.
- **base px.** For display this is the headline size, i.e. the start question.
- **ratio.** The modular-scale ratio. See "How sizes move" below.
- **tracking** (letter-spacing, in em) and **line-height.**
- **features.** Chips such as `tnum`. Click a chip once to turn the feature on, again to turn it off,
  and a third time to unset it. The **raw** field takes any `font-feature-settings` value.
- **Main only: small labels.** Main-role text at or below "label ≤" px gets `uppercase`, `small-caps`
  (as `all-small-caps`), `lowercase` or `capitalize`, plus extra label tracking.

**A / B** compares versions. **A** is the type in the code now and **B** is your settings. Hold **Alt**
to peek at A. The specimen in the panel follows whichever one is selected.

## How the preview works, and why apply gives the same result

1. The role tokens are set inline on `:root`: `--sans`, `--sans-weight`, `--sans-size`, `--sans-ratio`,
   `--sans-lh`, `--sans-tracking`, `--sans-features`, `--sans-vs`, the matching `--display-*` and
   `--mono-*` tokens, `--display-vs` and `--label-*`. They are defined in `base.css` `:root`. Their
   defaults equal the type before the panel existed, so they cause no visual change.
2. Most font sizes are written into the CSS directly, for example `font: 400 13px/18px var(--sans)`.
   The panel fetches every `/web/css/*.css` and runs `transformCss()` over it. It injects the result as
   a `<style>` and disables the original `<link>`.
3. `scripts/apply_fonts.py` contains a line-for-line Python copy of `transformCss()`. A test checks that
   both produce byte-identical CSS for every stylesheet.

### How sizes move

Each declaration belongs to a role. That role comes from the `var(--serif|--mono|--sans)` in the same
rule. If the rule has none, the role comes from another rule with the same selector, or else it is
main. Then:

- **size:** `new = base × (old / oldBase) ^ (ln ratio / ln oldRatio)`. With the same ratio, every size
  scales in proportion to the base. A larger ratio pushes small sizes smaller and large sizes larger
  around the base; a smaller ratio pulls them together. `clamp()` works because each `px` value inside
  it is mapped this way.
- **line-height:** unitless values are multiplied by `new lh / old lh`. `px` values also follow the size.
- **tracking:** existing letter-spacing values shift by the difference. Display and mono rules also get
  their own tracking, so the main role's tracking doesn't leak into them.
- **weight:** explicit weights shift by the difference, e.g. 400→450 also turns 500 into 550.
- **features:** display and mono features are appended to that role's rules. Mono axes are appended the
  same way.
- **labels:** the transform and label tracking are appended to main rules at or below the label size.

When a setting equals the current token, nothing is written, so the default settings change no file.

## Export → apply

**Export JSON** copies the JSON to the clipboard and downloads `pricemonkey-fonts.json`:

```json
{
  "version": 1,
  "roles": {
    "main":    { "family": "Geist", "fallback": "system-ui, sans-serif", "weight": 420, "weights": [400, 500],
                 "axes": {}, "size": 15.5, "ratio": 1.2, "letterSpacing": -0.005, "lineHeight": 1.45,
                 "features": "\"tnum\" 1, \"ss01\" 1",
                 "labels": { "transform": "uppercase", "letterSpacing": 0.05, "maxSize": 11 } },
    "display": { "family": "Newsreader", "axes": { "opsz": 72 }, "size": 70, "ratio": 1.25, "...": "..." },
    "mono":    { "family": "JetBrains Mono", "size": 12.5, "...": "..." }
  },
  "googleFontsUrl": "https://fonts.googleapis.com/css2?family=Newsreader:...&family=Geist:...&display=swap"
}
```

Units: `size` is in px, `letterSpacing` in em, and `lineHeight` is unitless. `axes` leaves out `wght`
because the weight is set separately.

**Import…** takes a pasted JSON or a file and loads it into the panel.

To make the export the site's type:

```sh
.venv/bin/python scripts/apply_fonts.py pricemonkey-fonts.json --dry-run   # see what would change
.venv/bin/python scripts/apply_fonts.py pricemonkey-fonts.json             # write it
```

The script makes these changes:

- In `agora/web/index.html`, it replaces the Google Fonts `<link>` href with `googleFontsUrl`. The URL
  must be `https://fonts.googleapis.com/css2?…`.
- In `agora/web/css/base.css` `:root`, it writes the new token values.
- In `agora/web/css/*.css`, it rescales sizes, line-heights, tracking and weights, and appends features
  and labels. It skips `devtools.css`.

After a run, the new values become the tokens. Running the same file again changes nothing, and the
panel's A becomes the applied type.

Limits:

- Label transforms are additive. Going from `uppercase` back to `none` with a later export doesn't
  remove the `text-transform` declarations already written; remove them by hand or from git.
- Some literal `font-variation-settings` are written for Fraunces only, such as the logo's
  `SOFT`/`WONK` and a few landing italics. A family without those axes ignores them.

# Dev logo panel

A second, separate local-only panel for the header logo: the monkey mark plus the "price**monkey**" wordmark.
It changes the logo only. The wordmark keeps the applied display font (Fraunces); to change the font itself, use
the type panel above.

- Code: `agora/web/js/logodev.js`, `agora/web/css/logodev.css`. `main.js` imports them through one line, only on
  `localhost`, `127.0.0.1` or `[::1]`.
- Apply script: `scripts/apply_logo.py`
- Tests: `tests/test_logodev.py`, which runs `tests/web/logodev.test.mjs` in node.

## Open it

- open `http://localhost:8765/?logodev=1` (`?logodev=0` keeps it closed)
- press **Ctrl+Shift+L** or **Cmd+Shift+L** to toggle the panel

Drag the header to move the panel. **–** collapses it and **×** closes it. When custom settings are active and the
panel is closed, a "custom logo" pill appears in the bottom left; click it to reopen. Settings and the panel
position are kept in `localStorage`.

## What you can set

| Group | Controls | Token(s) in `base.css` `:root` |
|---|---|---|
| Mark | image size (width in px; height = width × 0.85), gap to the text, tilt, hover wiggle on/off + hover tilt | `--logo-mark-w`, `--logo-gap`, `--logo-tilt`, `--logo-hover-tilt` (0deg = no wiggle) |
| Vertical centring | centre on the x-height or cap-height middle (or a custom em value), fine nudge in px or em (+ = text lower), guides | `--logo-center`, `--logo-nudge` |
| Wordmark | size, weight and hover weight (the `wght` axis of the same font), letter-spacing (em), case, italic for "price" and "monkey" separately | `--logo-size`, `--logo-weight`, `--logo-hover-weight`, `--logo-tracking`, `--logo-case`, `--logo-price-style`, `--logo-monkey-style` |
| Colours | "price" and "monkey", light and dark separately; a preview switch (auto / light / dark) | `--logo-price-light`, `--logo-monkey-light`, `--logo-price-dark`, `--logo-monkey-dark` |
| Footer mark | size and nudge of the small mark before the footer line | `--logo-foot-w`, `--logo-foot-nudge` |

Colours take `#rrggbb` (from the picker or typed) or a token such as `var(--ink)`.

**A / B** compares versions. **A** is the logo in the code now and **B** is your settings. **Reset** goes back to A.

### How the centring works

The logo is a single line of inline content. The mark has
`vertical-align: calc(var(--logo-center) - var(--logo-mark-w) * 0.425 + var(--logo-nudge))`, which puts the middle of
the mark exactly `--logo-center` above the text baseline. `--logo-center` is half of the wordmark's x-height
(`0.2325em`, measured from rendered pixels of Fraunces italic at opsz 48) or half its cap-height (`0.35em`, which
the panel picks when you choose UPPERCASE). Because the value is in em, it holds at any wordmark size, on desktop
and phone. The footer mark uses `vertical-align: middle`, which is the middle of the text's x-height for whatever
font the footer uses.

**guides** draws a red line through the middle of the mark and a blue band over the x-height or cap-height. When
the logo is centred, the red line runs through the middle of the band.

## Export → apply

**Export JSON** copies the JSON to the clipboard and downloads `pricemonkey-logo.json`:

```json
{
  "version": 1,
  "logo": { "markWidth": 40, "gap": 8, "tilt": 0, "hoverTilt": -7, "size": 26.31, "weight": 400, "hoverWeight": 500,
            "tracking": -0.007, "center": 0.2325, "nudge": 0, "nudgeUnit": "px", "footerWidth": 19, "footerNudge": 0,
            "wiggle": true, "case": "lowercase", "priceItalic": true, "monkeyItalic": true,
            "colors": { "light": { "price": "var(--ink)", "monkey": "#4E3818" },
                        "dark":  { "price": "var(--ink)", "monkey": "#D9B98C" } } },
  "vars": { "--logo-mark-w": "40px", "...": "..." }
}
```

`vars` is for reading only. The script works from `logo` and checks it the same way the panel's Import does:
numbers are clamped to the slider ranges, and unknown values keep the current ones.

```sh
.venv/bin/python scripts/apply_logo.py pricemonkey-logo.json --dry-run   # list the token changes + a diff
.venv/bin/python scripts/apply_logo.py pricemonkey-logo.json             # write them
```

The script changes only the `--logo-*` values in the first `:root` block of `agora/web/css/base.css`, and only the
values that differ. Running it again with the same file changes nothing. After a run, the panel's A is the new logo.

Note: the logo's size, weight and tracking are now `--logo-*` tokens, so `apply_fonts.py` no longer rescales the
logo with the display role. The logo panel controls them.
