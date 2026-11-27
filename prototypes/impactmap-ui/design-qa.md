# Design QA — ImpactMap A6.1

Date: 16.11.2026. Target: выбранный владельцем displayed option2, Investigation workbench.

**Source visual truth:** `qa/source-reference.png`, byte-identical copy of `../../docs/product/ui-admin-2026-11-16/visuals/workbench.png`.
**Implementation:** `http://127.0.0.1:18087/#/changes/pr5`, `qa/03-desktop-revised.jpg`.
**Viewport/state:** 1487×1058 CSS px, devicePixelRatio1, PR5 generation2/risk, operator simulation, light theme, scrollY0. Source1487×1058 PNG; implementation1487×1058 JPEG. No density resampling. Additional checks1440×1024 and390×844.

**Full-view comparison:** `qa/04-comparison-final.jpg` — actual source above actual implementation in one browser-captured comparison input; not independent views presented as a comparison. `qa/compare-final.html` reproduces arrangement without changing source images. First horizontal arrangement clipped the right image and was rejected/replaced by the vertical comparison.

**Focused comparison:** `qa/11-comparison-evidence.jpg` — source evidence above implementation evidence, derived from source and final actual screenshot through `qa/compare-focus.html`. The complete source images remain unchanged. Compared path, commit/line label, typography and code readability.

## Findings and iteration history

- **[P2, fixed] Main-region proportions/type scale.** Initial `qa/01-desktop-initial.jpg` / combined `qa/02-comparison-initial.jpg`: sidebar204/list340 shifted main content18px left relative to target; smaller risk heading/status labels and primary button weakened hierarchy. Fixed columns211/351, main padding30, heading34, badge16 and primary width278. Revised evidence: `qa/03-desktop-revised.jpg`, combined `qa/04-comparison-final.jpg`; region starts and above-fold hierarchy now match the selected composition.
- **[P2, fixed] Narrow-screen source-path overflow.** Actual390px page overflowed to596px due to min-content width in a flex notice. Evidence: `qa/07-mobile-partial-before.jpg`. Fixed min-width0 on notice child and anywhere wrapping for its text. Retest: document width390 at viewport390; `qa/07-mobile-partial.jpg` inspected after saving. Code itself scrolls inside its dedicated focusable panel, rather than widening the page.
- **[P2, fixed] Multiline link hit areas.** On390px, inline wrapped operator/example links did not consistently activate their intended destination using browser clicks. Separated operation links into block targets and used inline-block hit area for text links. Retested Kaiten→binding→PR5 and example-after-fix journeys through actual clicks; `qa/08-mobile-fixed.jpg` records the resulting generation3 view.
- **[P2, fixed] Unknown route accepted inherited object properties.** Independent reviewer found `cases[route.id]` accepted `toString`/`constructor`/`__proto__`. Browser reproduction showed undefined title and incompatible-result screen. Fixed `Object.hasOwn` and fallback title; verified direct `toString`, `constructor` and `__proto__` routes now give «Страница не найдена», with no undefined output. This was a correctness finding, not visual drift.

## Required fidelity surfaces

- **Fonts/typography:** system sans-serif fallback, bold compact headings, monospace for provenance/code. Computed stack includes Inter/-apple-system/system-ui/Segoe UI/Arial. No external font download. Exact raster font from generated image is unavailable; residual glyph/weight differences are P3, not a claim of pixel identity. Body/heading hierarchy and wrapping directly compared.
- **Spacing/layout:** same narrow global navigation, change list and main workspace, compact topbar, three-state row, amber risk/notice and evidence below. Desktop1440 and exact-reference1487 inspected; narrow390 reflows to readable stacked sections. No actionable clipping remains in checked routes.
- **Colors/tokens:** white/off-white base, dark forest-green selected state, pale green technical statuses, amber risk, separate red errors. Solid colors rather than generated gradients. Technical green states never replace the amber risk warning.
- **Images/assets:** no illustration/photo assets in source. Text wordmark remains text; standard outline icons are vendored Tabler SVGs with original MIT license and per-file provenance. No handcrafted SVG or CSS illustration substitute. All visible images loaded in browser; no broken asset icons in final view.
- **Copy/content:** Russian user-facing UI. Corrected generated «без параметров страницы» to the narrower observation «В обследованном фрагменте найден вызов Orders». Only the known author-fixture code line is shown; generated surrounding source lines were intentionally not invented. Extra search/fixtures/limits implement the approved scenarios and remain labelled synthetic. PR4/PR3 show real intended failure/partial example states instead of copying the image's all-success list.

## Interaction/accessibility verification

Browser-tested five approved journeys on1440 and390: select result, evidence focus/code, current error with prior STALE, operation→connection/binding, prepared generation3 example. Search match/no-match/clear tested. Empty, closed, incompatible and unknown-code states inspected. Reviewer simulation hides operator navigation and direct operations URL shows explicit role restriction; switching back restores it. This is not authentication testing.

Keyboard: Enter activates evidence action and focuses `evidence-heading`; dialog opens with labelled heading, Escape closes it and returns focus to source button. Long code panel is focusable/scrollable. Route changes focus heading. Declared text-color pairs checked computationally: selected7.61:1, muted6.00:1, amber6.73:1, error6.38:1; this is not all rendered contrast combinations. No full screen-reader or WCAG compliance claim; zoom/OS high-contrast/browser matrix and human usability remain future work.

Console: final inspected error/warn logs empty. Runtime screenshot/DOM shows every image loaded. Static server CSP `connect-src 'none'` and no app fetch/API calls: no external writes. No new full repository suite run: core/service source unchanged and this is a throwaway frontend; browser scenarios are the meaningful acceptance check.

## Open questions / residual limits

No blocking visual questions for this prototype. Owner has not yet performed a usability walkthrough. Real sessions/grants/source evidence API/connections metadata and deployment are A6.2–A6.5, not implemented here. Mobile list precedes content; a future iteration may collapse it after selection, but all checked paths remain usable.

## Implementation checklist

- [x] Selected exact displayed option2 and preserve visual truth.
- [x] Compare actual rendered page and reference together; fix P2 composition.
- [x] Inspect focused evidence comparison.
- [x] Fix390px overflow and multiline link targets; repeat actual journeys.
- [x] Fix reviewer route finding; verify fallback.
- [x] Check console/assets and record verification boundaries.

**Follow-up polish:** P3 exact font/icon weight matching; consider more compact mobile change list after user feedback. These do not block the author-prototype handoff.

final result: passed

## Typography revision2 — owner feedback,16.11

Owner reviewed prototype and requested a smaller font while accepting the overall direction. This overrides the larger text scale of the generated visual; no new design choice requested. Body14px, desktop h128px (was36), risk heading26px (was34), mobile h123px. Composition,14px baseline readability and44px controls retained. Browser checks1440×1024 and390×844 showed no horizontal overflow; [desktop](../../docs/operations/a6-2-2026-11-16/prototype-compact-desktop.jpg) and [mobile](../../docs/operations/a6-2-2026-11-16/prototype-compact-mobile.jpg) saved and opened. These replace earlier CSS evidence for current typography; previous comparison artifacts remain historical. Font reduction is intentional owner-requested drift, not an unresolved fidelity finding.

Typography revision2 final result: passed
