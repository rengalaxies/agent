"""Bounded real inference qualification; no source code or confidential input sent."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

ENDPOINT = 'https://foundation-models.api.cloud.ru/v1/chat/completions'
MODEL = os.getenv('CLOUDRU_LLM_MODEL') or 'openai/gpt-oss-120b'


def main():
    report = {'model': MODEL, 'endpoint': ENDPOINT, 'scope': 'synthetic connectivity probe only',
              'max_requests': 2, 'max_completion_tokens_per_request': 16,
              'probes': [], 'agent_scenario': 'NOT_RUN', 'cost': 'NOT_MEASURED'}
    for name in ('CLOUDRU_FOUNDATION_API_KEY', 'CLOUDRU_WORKFLOW_API_KEY'):
        key = os.getenv(name)
        row = {'credential_name': name, 'status': 'BLOCKED_MISSING_CREDENTIAL'}
        if key:
            request = urllib.request.Request(ENDPOINT, data=json.dumps({
                'model': MODEL, 'messages': [{'role': 'user', 'content': 'Reply OK.'}],
                'max_completion_tokens': 16, 'temperature': 0}).encode(),
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    value = json.loads(response.read(100000))
                row = {**row, 'status': 'PASS_API_RESPONSE',
                       'has_choices': bool(value.get('choices')), 'usage': value.get('usage', {})}
            except urllib.error.HTTPError as exc:
                row = {**row, 'status': 'BLOCKED_HTTP', 'http_status': exc.code}
            except Exception as exc:
                row = {**row, 'status': 'BLOCKED_REQUEST', 'error_class': type(exc).__name__}
        report['probes'].append(row)
        if row['status'] == 'PASS_API_RESPONSE':
            break
    Path('lab-model-probe.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
