"""Build blind offline questionnaire. Does not load oracle/results/metrics."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from datamesh_release_protocol.loaders import load_catalog


def main():
    p=argparse.ArgumentParser();p.add_argument('--scenarios',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--map-source',type=Path);a=p.parse_args()
    cases=[s.model_dump(mode='json') for s in load_catalog(a.scenarios)]
    for c in cases: c['assessment_block']='semantic_quality'
    if a.map_source:
        variations=[('coverage_missing','Подтверждённый реестр состава потребителей отсутствует.'),
            ('coverage_candidate','Реестр состава потребителей предложен агентом, но ещё не подтверждён регистратором.'),
            ('obligation_candidate','Все показанные требования имеют статус candidate и ещё не подтверждены владельцами.'),
            ('usage_expired','Все показанные регистрации использования истекли до фиксации снимка.'),
            ('missing_consumer','В подтверждённом реестре дополнительно зарегистрирован потребитель X, но его использование и требования отсутствуют.'),
            ('wrong_authority','Все требования подтверждены производителем; полномочий подтверждать требования потребителей у него нет.'),
            ('constitution_conflict','Одновременно действуют две разные версии одной конституции; правило разрешения конфликта не задано.'),
            ('attribute_unresolved','Все использования ссылаются на поля без подтверждённых записей атрибутов соответствующей версии.'),
            ('usage_inactive','Все показанные использования помечены inactive, но потребители по-прежнему входят в обязательный реестр.'),
            ('obligation_revoked','Все показанные требования отозваны до фиксации снимка.')]
        for i,scenario in enumerate(load_catalog(a.map_source)):
            base=scenario.model_dump(mode='json')
            for variant in ('complete','incomplete'):
                c=json.loads(json.dumps(base));kind,condition=variations[i%len(variations)]
                c['scenario_id']='MAP-'+base['scenario_id']+'-'+variant
                c['assessment_block']='knowledge_sufficiency'
                c['metadata_context']={'registration_boundary':'Только зарегистрированные потребители данной платформы',
                    'snapshot_status':'Снимок зафиксирован; после фиксации ничего не менялось.',
                    'default_evidence':'Производитель, команды, контракт, атрибуты, использования, требования, реестр и конституция подтверждены уполномоченными владельцами; сроки действуют. Реестр в точности содержит показанных потребителей. Все обязательные требования показаны.',
                    'exception':'Нет исключений.' if variant=='complete' else condition,
                    'task':'Оцените разрешение выпуска по всей совокупности семантики и достаточности карты. Исключение заменяет соответствующий факт из default_evidence. Не считайте неподтверждённое требование действительным доказательством нарушения.'}
                cases.append(c)
    payload=json.dumps(cases,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    version=hashlib.sha256(payload.encode()).hexdigest()
    html=Path(__file__).with_name('questionnaire-template.html').read_text()
    html=html.replace('__CASES__',payload.replace('</','<\\/')).replace('__HASH__',version)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(html,encoding='utf-8')
    a.output.with_suffix('.catalog.json').write_text(json.dumps({'catalog_hash':version,'scenario_ids':[c['scenario_id'] for c in cases],'blocks':{block:[c['scenario_id'] for c in cases if c['assessment_block']==block] for block in sorted({c['assessment_block'] for c in cases})}},indent=2))
    print(f'{len(cases)} cases; blind content hash {version}; {a.output}')

if __name__=='__main__':main()
