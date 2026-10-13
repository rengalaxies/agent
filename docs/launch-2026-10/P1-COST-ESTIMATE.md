# Cloud.ru P1 pricing - 13 October 2026

Official active Cloud.ru Evolution Compute tariff version 260619, effective 2026-06-29, with VAT 22%: https://cdn.cloud.ru/docs/legal/tariffs/evolution/current-version/evolution-compute.pdf

## Baseline 30-day schedule
- UI: `gen-2-4` assumed standard full-share 2vCPU / 4GiB, 720h x 2.9707 RUB/h = **2138.90 RUB**.
- Core: `gen-8-32` assumed standard full-share 8vCPU / 32GiB, 160h x 15.9576 RUB/h = **2553.22 RUB**.
- Disks: 30+80=110 GiB SSD NVMe x 720h x 0.01586 RUB/GiB/h = **1256.11 RUB**.
- Public IP: 1 x 720h x 0.2074 RUB/h = **149.33 RUB**.
- Proposed public sNAT for private core: 1 x 720h x 0.2074 RUB/h = **149.33 RUB** (NOT included in current 15-resource Terraform plan).
- Fixed estimate for these items: **6246.89 RUB/month**.
- Outbound data: published rate 0.00366 RUB/MB, example 10 GiB ~ **37.48 RUB**.
- Backup storage: published rate 0.005856 RUB/GiB/h, illustrative 80 GiB x 720h ~ **337.31 RUB** (backups NOT yet implemented; storage volume is an assumption).
- Subtotal with examples: **6621.68 RUB/month**.
- 25% headroom: **8277.10 RUB/month**, EXCLUDES token/LLM spend, domain/DNS, any extra resource charges and potential differences in SKU guarantees.

Important: This is NOT an issued Cloud.ru quote. Verify that selected `gen-` flavor corresponds to the full-share rate, that stopped VM compute is not billed, and that egress/NAT connectivity is supported for this project and its subnet. At 720h for core instead of 160h, add **8936.26 RUB/month**, making this budget unsuitable for always-on core.

## Hard cost controls
- Plan-only no paid provisioning.
- Cap core operating schedule at approved hours, with operator-reviewed start/stop automation; not yet implemented.
- Set Cloud.ru account budget alert at a threshold lower than approved monthly maximum using platform billing controls when available; do not claim hard spending enforcement without a documented feature.
- LLM token procurement is an independent explicit budget approval.
- Do not confuse cost estimation with confirmed price or booking.

## Project isolation
Project UUID `20853297-65b7-42a8-af40-25c8d2df4e11`. No other Cloud.ru project is authorized.
