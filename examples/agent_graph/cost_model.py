"""Scenario arithmetic, not measured throughput, a quote or a commercial price."""
import json


def scenario(changes, initial_input, update_input, input_per_change, output_per_change,
             retry_fraction=0.2, output_input_ratio=0.1):
    input_tokens = (initial_input + update_input + changes * input_per_change) * (1 + retry_fraction)
    output_tokens = ((initial_input + update_input) * output_input_ratio
                     + changes * output_per_change) * (1 + retry_fraction)
    return dict(changes=changes, initial_input=initial_input, update_input=update_input,
                input_per_change=input_per_change, output_per_change=output_per_change,
                retry_fraction=retry_fraction, input_tokens=input_tokens, output_tokens=output_tokens,
                deepseek_flash_peak_usd=(input_tokens * 0.30 + output_tokens * 1.20) / 1e6,
                cloud_haiku_reference_rub=(input_tokens * 196.42 + output_tokens * 982.10) / 1e6,
                human_hours_assumption=8 + changes * (3 + 0.1 * 10) / 60,
                human_cost_rub_at_2000_per_hour=(8 + changes * 4 / 60) * 2000)


def report():
    weights = [{"parameters_billions": p, "bf16_gib_floor": p*1e9*2/2**30,
                "fp8_gib_floor": p*1e9/2**30, "int4_gib_floor": p*1e9/2/2**30}
               for p in (30.5, 80, 685)]
    kv_bytes_per_token = 2 * 48 * 4 * 128 * 2
    return dict(kind="ESTIMATES_NOT_MEASUREMENTS", currency_conversion=None,
                prices_checked="2026-10-21", weight_floors=weights,
                qwen30_kv_bytes_per_token_bf16=kv_bytes_per_token,
                kv_gib={str(n): kv_bytes_per_token*n/2**30 for n in (16384, 32768, 262144)},
                scenarios=[scenario(100, 400000, 100000, 40000, 4000),
                           scenario(1000, 2000000, 500000, 40000, 4000),
                           scenario(10000, 10000000, 2000000, 40000, 4000)],
                vm_2xa100_80gb_rub_hour=732, vm_8h_rub=732*8, vm_730h_rub=732*730,
                budget_proposal_not_authorization=dict(gpu_hours=8, vm_rub=5856,
                                                       storage_network_contingency_assumption_rub=1000, total_rub=6856))


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
