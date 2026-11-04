# Bitbucket Source Probe Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, then one fresh reviewer. Preserve the owner's short iteration and proceed without another design approval round for the already requested additive batch.

**Goal:** Provide validated Bitbucket installation configuration and a read-only CLI probe with no state/worker side effects.
**Architecture:** Strict config models feed the existing reader through a dedicated factory. A probe returns only complete identity/ref/PR metadata; CLI dispatches before `_service`. Runtime build explicitly rejects Bitbucket configuration until subsequent runtime support.
**Tech Stack:** Python, Pydantic, existing HttpClient, unittest with actual synthetic HTTP.
**Spec:** docs/superpowers/specs/2026-11-02-bitbucket-source-probe-design.md

## Global constraints

Additive GitHub/Jira behavior; no credentials in configuration/output; no external APIs, paid resources, VM or release/pin changes. No state opening or credential loading before runtime refusal. Production API fixed to https://api.bitbucket.org/2.0; existing loopback test flag only.

## Review focus

Wrong repository/workspace UUID; graph ID collisions including GitHub defaults; partial later-page/repository failure; empty repository semantics; missing/invalid credentials and accidental analyzer/state creation. Pin each with a test.

## Task 1 — configuration, probe, CLI and evidence

Files: config.py (strict models, factory, runtime guard); new bitbucket_probe.py (complete report); __main__.py (early dispatch); new test_bitbucket_probe.py; this plan/design and report/example.
Interfaces: ServiceConfig.bitbucket; build_bitbucket_reader(config,env_secret); probe(config,env_secret) -> dict; CLI `python -m agent_service bitbucket-probe --config FILE`.

- [x] Write failing config/probe/CLI tests using an actual HTTP stand and nonexistent state path.
- [x] Run RED; implement the smallest config/factory/report/early dispatch and runtime guard.
- [x] Run GREEN plus existing reader/connection/contract regressions and workflow Ruff.
- [x] Attempt whole Core discovery; keep runtime/platform limitations explicit. Independent final review and any test-first fixes.
- [x] Save example, evidence, report and rollback; commit; publish separate draft PR stacked on #93. No merge/release/deploy.
