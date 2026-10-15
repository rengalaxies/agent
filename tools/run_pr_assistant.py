"""Local advisory artifact generation; never posts a GitHub comment or deploys."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import yaml
from datamesh_release_protocol.change_assistant import analyze_change
from datamesh_release_protocol.dependency_import import import_sql, import_manifest
from datamesh_release_protocol.models import Scenario, BaselinePolicy

ROOT = Path(__file__).resolve().parents[1]


def load_example(path=None):
    data = json.loads(Path(path or ROOT / 'examples/pr-assistant/input.json').read_text())
    scenario_path = ROOT / 'scenarios/development' / (data['development_scenario'] + '.yaml')
    if scenario_path.resolve().parent != (ROOT / 'scenarios/development').resolve():
        raise ValueError('only development fixtures are supported by this diagnostic CLI')
    scenario = Scenario.model_validate(yaml.safe_load(scenario_path.read_text()))
    policy = BaselinePolicy.model_validate(yaml.safe_load((ROOT / 'policies/v1-ind.yaml').read_text()))
    return data, scenario, policy


def artifacts(data):
    return [import_sql(data['consumer_sql'], data['consumer_id'], data['consumer_schemas'], data['source_ref']),
            import_manifest(data['manifest'], data['source_ref'], data['bindings'])]


def report(data, scenario, policy):
    return analyze_change(scenario, policy, artifacts(data), data['registration'], data['requirement_states'],
                          datetime.fromisoformat(data['evaluated_at']), old_sql=data['old_sql'],
                          new_sql=data['new_sql'], schemas=data['schemas'], tables=data['tables'],
                          expected=data['expected'])


def write_report(result, output):
    output.mkdir(parents=True, exist_ok=True)
    prior = output / 'analysis.json'
    if prior.exists() and json.loads(prior.read_text()).get('report_hash') != result['report_hash']:
        raise ValueError('use a fresh output directory for a different report; avoid stale repair artifacts')
    (output / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# Разбор изменения данных', '', f"Решение: {result['decision']} (рекомендация)", '',
             '## Изменение', '', '```diff', result['diff'], '```', '', '## Затронутые потребители', '']
    for item in result['affected']:
        lines.append(f"- {item['consumer_id']}: владелец {item['owner']}, требование {item['obligation_id']}, источник {item['requirement_source']}")
    lines += ['', '## Пробелы', ''] + [f'- {gap}' for gap in result['gaps'] or ['Не обнаружены в предоставленной области; полнота организации неизвестна.']]
    lines += ['', '## Следующее действие', '']
    candidate = result['proposed_artifact']
    if candidate:
        (output / 'compatibility.sql').write_text(candidate['sql'])
        (output / 'compatibility-contract.json').write_text(json.dumps(candidate['contract'], ensure_ascii=False, indent=2) + '\n')
        (output / 'regression-fixture.json').write_text(json.dumps(candidate['regression_test'], ensure_ascii=False, indent=2) + '\n')
        lines += [f"Подготовлена совместимая версия рядом с новой. Повторная проверка: {candidate['typed_recheck']}.", '',
                  'Файлы: compatibility.sql, compatibility-contract.json, regression-fixture.json.', '',
                  'Владельцу нужно проверить применимость и маршрутизацию потребителей. Автоматического применения нет.']
    else:
        lines += ['Разобрать указанные пробелы или продолжить обычное ревью. Новое обязательное согласование не создается.']
    lines += ['', 'Ожидаемые результаты и подтверждения в демо синтетические. Это не результат пилота.', '']
    (output / 'pr-review.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data, scenario, policy = load_example(args.input)
    result = report(data, scenario, policy)
    write_report(result, args.output)
    print(json.dumps(dict(decision=result['decision'], report_hash=result['report_hash'],
                         output=str(args.output)), ensure_ascii=False))
