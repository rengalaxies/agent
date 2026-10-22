---
name: HTTP graph demo
description: A quiet inspection workspace connecting API changes, exact source and observed consequences.
colors:
  paper: "#f4f4f0"
  surface: "#ffffff"
  ink: "#1d302f"
  muted: "#536460"
  line: "#cdd6d0"
  teal: "#146356"
  teal-light: "#e4f0eb"
  amber: "#795009"
  amber-light: "#fff2d7"
  red: "#a22e2c"
  red-light: "#fff0ec"
typography:
  body:
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    lineHeight: 1.55
  display:
    fontSize: "clamp(25px, 2.6vw, 36px)"
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  source:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "12px"
    lineHeight: 1.7
rounded:
  panel: "12px"
  control: "8px"
  field: "7px"
---

# HTTP graph demo interface

## Overview

Scope: `src/agent_graph_demo/web`, the separate HTTP application prescribed by PR29. The existing `ui/` research examples are a historical surface. The implemented Russian interface is a quiet, light inspection workspace for laptop demonstrations, with a sequential mobile reading order. Exact evidence, conditional risks and observed checks remain visibly distinct.

This document records the implementation and the B/E desktop and 390px captures in `work/acceptance-final/`. Visual review found no blocking issues; final acceptance and test results are recorded separately. These captures establish neither model qualification nor a release decision.

## Colors

Warm paper surrounds white panels. Dark ink carries primary text; muted text supplies context and limitations; thin neutral lines divide sections. Deep teal identifies the primary action, selected dependency and selected scenario; its light tint also marks a successful applicable check. Amber findings describe conditional risks. Red check cards describe observed failures, and red status text reports request errors. Historical checks use muted text on a neutral background. Every status includes words, counts or labels in addition to colour.

## Typography

System sans is used throughout the interface. The task heading uses the display scale; section headings are 19px/1.3, subsection headings 16px/1.4. Labels and supporting copy are generally 13px. Paragraph width is capped at 72ch. Monospace is reserved for exact source, diff, operator commands and diagnostics; source reduces to 11px on narrow screens. Code preserves whitespace and line numbers.

## Layout

The desktop container is centred, capped at 1620px and padded 30px vertically / 28px horizontally. Header, task introduction, version strip and change controls precede a shared white workspace. Its three columns are map, change/impact/checks and evidence, with proportions 0.95:1.35:1, minimum widths 250/310/250px and 23px internal padding. Thin dividers provide stable boundaries.

At 1100px and below, map and story remain in two columns and evidence spans the next row. At 650px and below, including 390px, the workspace becomes map → story/checks → evidence; header and state strip wrap, the session selector fills the width, actions wrap into two columns, main padding becomes 22px / 16px and panel padding 20px / 16px. History becomes one column. The page fits the viewport; source, diff and diagnostics scroll inside bounded code boxes. Source is 180–470px tall; other code boxes are capped at 330px.

## Elevation & Depth

No shadows. White surfaces, restrained tinted state backgrounds and one-pixel borders provide separation. The selected relationship diagram is a small tonal inset, not a decorative overview graph.

## Shapes

Panels and the state strip use the panel radius; buttons and code blocks use the control radius; fields use the field radius. Buttons have at least 42px height, 9px / 13px padding and a visible border. Fields are full width; the correction textarea can resize vertically.

## Components

- **State and actions:** proposed source/revision, confirmed running version, current applicable check summary and assessment freshness have separate labels. The summary reports each consumer's observed count out of 250 and status, or says no current check exists. Freshness refers to the last explicit assessment. Preparing B/D/E changes source for analysis; service execution remains an operator action. Busy actions are disabled; queue, running, partial, failure, cancellation and unknown-after-restart states use explicit Russian text. Retry preserves the request key. Operator/viewer access is labelled.
- **Dependency selection:** buttons are generated from actual CLI records and show consumer → service, operation and observed request pattern. They support keyboard activation and `aria-pressed`; selected tint and border accompany the state. The SVG describes only the selected relationship and updates its accessible label. Loading a graph clears the prior SVG selection and returns it to a choose-dependency placeholder.
- **Evidence:** selection immediately clears the old usable evidence, disables correction and shows textual loading placeholders. Successful responses show repository, path, exact line range, snapshot version and quote through `textContent`. A failed response says evidence is unavailable and offers retry by selecting the relationship again. Loading/failure use the existing source surface and text palette; request errors also appear in the red live status. Session, graph and evidence request tokens reject late responses from superseded selections or contexts. On mobile, successful evidence loading moves focus to its heading and scrolls that heading into view.
- **Trust boundaries:** the map is labelled static analysis; coverage and gaps remain explicit. Amber findings state that a graph test was not run and release approval was not given. Model candidates are labelled unconfirmed and never become graph edges; this demo states that the model is unavailable. Human corrections are separate versioned decisions tied to evidence, with optional supersession; they do not rewrite source or the observed call. Correction is disabled for viewers, historical results, stale contexts and pending work. Runtime cards are observations from the separate operator runner; their provenance disclosure states their limits. External reports remain `EXTERNAL_REPORTED` and explicitly lack independent confirmation.
- **Checks and history:** the latest applicable runtime check is expanded; previous checks sit in a collapsed disclosure and use historical styling. Counts include missing, duplicate and unexpected IDs. Saved job history remains visible below the workspace, with version/revision context and a return-to-current control when opened. Opening history does not change the proposed version. Diff, gaps, operator action, correction form and diagnostics are collapsed by default.
- **Keyboard and feedback:** a skip link reaches the workspace; controls, links, disclosure summaries and source have visible teal focus outlines (3px with 3px offset). Source is keyboard focusable for internal scrolling. General feedback uses a polite live status region. Buttons use a short background transition; reduced-motion preference removes transitions.

## Do's and Don'ts

- Do preserve exact source, version, applicability and provenance beside the evidence they qualify.
- Do keep current checks easy to scan while retaining previous checks and immutable job history.
- Do keep unknown, incomplete and unavailable states explicit; an empty map or absent finding is not evidence of safety.
- Don't merge static discovery, a model candidate, human correction, runtime observation or external report into one success state.
- Don't use decorative illustrations, invented metrics or the historical research UI's canned ACCEPT/REJECT presentation for this evidence workflow.
