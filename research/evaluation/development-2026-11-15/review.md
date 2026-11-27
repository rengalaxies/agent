# Fresh review и один проход исправлений

Один fresh reviewer, read-only диапазон49cd917..04fcbec, model gpt-6-astra/high по executing-plans. Первая попытка review прервалась usage limit до результатов; после «продолжи» тот же reviewer завершил тот же обзор. Повторного ревью/второго reviewer не было. Все7 findings приняты по фактическому влиянию; deferred minors нет.

| Приоритет | Воспроизведённый дефект | Исправление и тест RED→GREEN |
|---|---|---|
| P1 | Два requests на одной строке получали один ID; явный замещал неявный | ID включает column offset; test_same_line_calls_keep_the_implicit_size_alert_in_either_order |
| P1 | FastAPI Annotated/Query alias/Body не доказывают query binding имени page_size | Закрытая грамматика скалярной аннотации, unknown для остальных и согласование всех declarations; test_fastapi_alias_body_and_non_scalar_annotations_cannot_prove_query_override |
| P1 | OpenAPI component response via $ref менялся вне сравнения | Basis включает context пути и non-path document settings/components; test_referenced_response_schema_change_prevents_default_only_exemption |
| P1 | Другой handler того же provider вызывался как helper, его изменение скрывалось | Все changed/added/removed операции индексируются до operation_id filter, соседнее изменение запрещает exemption; test_other_handler_used_as_helper_disqualifies_default_only_exemption |
| P2 | params page_size='' освобождал от проверки, URL page_size= — нет | Пустое значение одинаково не доказывает override; test_empty_dict_and_url_query_values_both_keep_alert |
| P2 | Mixed delta без consumer получал сводку Default-only | Любой UNCLASSIFIED_OPERATION_CHANGE участвует в uncertainty независимо от findings; test_exempted_default_does_not_hide_unclassified_delta_without_callers |
| P2 | Выбранный operation_id учитывал opaque edit другого provider repo | Provider repos для opaque comparison ограничены evidence выбранной операции; test_selected_operation_ignores_opaque_edit_in_other_provider_repository |

17 scope tests до исправлений имели10 failing assertions/subcases; после исправлений28/28 с прежними discovery neighbours прошли. Один fix pass сохранён6bc5ca2. Затем все269 graph tests прошли, новый полный author40 run v2 повторён на окончательном core. V1 сохранена SUPERSEDED; её красивые20/0/0 не скрыли дефекты соседних случаев. Исходная06/scorer/normalizer/oracle не менялись.

В большом параллельном project-run обнаружилось старое unit-ожидание service.test_pilot_preparation: оно требовало RECHECK после явного размера. Ожидание изменено на отсутствие нового alert с сохранённой EXPLICIT_PAGE_SIZE dependency; весь module3/3 прошёл. Это изменение unit-контракта вместе с намеренной функцией, не фильтр evaluator. Ошибка qualification fingerprint в том же процессе объяснена изменением source во время run; отдельный стабильный запуск evaluator+qualification39/39 прошёл. Все исходные неуспешные логи сохранены, в том числе service404 с1 superseded assertion/4Linux skips и project1190 с46fail/40error/4skip.

## Rulings по Declined to judge и решениям исполнения

- Независимая06/реальные эксперты остаются внешним обязательством; стоимость — эти40 и проценты не принимаются как независимый результат.
- FAILED/commit_unavailable сохраняется для DEV0039; стоимость — O-boundary остаётся5/6, метрика не подгоняется.
- Отдельная05 operation-removal/unmapped_call не входит в этот fix; стоимость — известный gap остаётся, новый profile7 ещё требует повторных нагрузочных измерений.
- MacOS RLIMIT_AS/symlink-temp guards, legacy tool import и CLI startup deadline рассматриваются отдельно от качества HTTP core; стоимость — весь project CI пока не зелёный. Защитные limits не ослаблялись. Tools import исправлен только окружением и16/16 recheck; CLI deadline recheck остался красным.
- Conservative module-constant/другой handler/contract-component basis допустимы: не строим произвольный Python call graph; стоимость — некоторые лишние проверки остаются возможны.
- Восстановлен прежний exact jsonschema dependency set в ignored work/, без изменения venv приложения; стоимость — этот PYTHONPATH нужен для воспроизведения tooling.
- Calibrate получил post-tuning disclosure и core drift guard; стоимость — evaluator hash закономерно новый, scorer/normalizer/пороги/labels прежние.
