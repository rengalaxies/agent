# A6.3 source review и исправления

Независимый reviewer проверил `b0c4104..dd738ec` и самостоятельно прошёл35 тестов UI view/scope/API.0 Critical,6 Important,1 Minor. Один финальный проход исправлений — `5d3502d`; после него62/62 focused tests и браузерные проверки. Повторное review не выдаётся за выполненное.

| Important | Воспроизведение RED | Исправление и GREEN |
|---|---|---|
| Hidden-candidate flags |1001 stamped, но withheld результата меняли публичные `has_more/scan_limited` |`has_more` только по дополнительной разрешённой строке; постоянный scan_budget1000 и одинаковая caveat; `test_many_withheld_candidates_do_not_reveal_hidden_existence` сравнивает полную projection с пустой БД |
| Список теряет публикацию/источник/время |В строке нет UNKNOWN/UTC/provider/kind |Разрешённая publication projection сохраняется в metadata; `test_list_exposes_authorized_publication_source_and_observation` |
| Native anchor вызывает повторное чтение и уводит фокус |2 GET, focused H1, evidence top2419px |popstate сравнивает pathname+search, evidence article focusable;0 GET, focus evidence-0, top20px — browser-checks.json |
| Logout оставляет соседнее видимое окно |Нет сигнала очистки между документами |Credential-free BroadcastChannel в обоих поверхностях; session→workbench и workbench→session, оба visible, после выхода private/account DOM отсутствуют |
| Nullable gap даёт ложный отказ |Валидный PARTIAL с repository:null скрыт |Null разрешён именно в валидированном optional gap.repository; foreign ID по-прежнему скрыт; `test_nullable_gap_repository_remains_partial_but_foreign_repository_is_denied` |
| Нет consumer/finding→its evidence |IDs ссылок теряются, два потребителя не имеют своих переходов |Числовые deduplicated anchors по finding.evidence_refs и affected.relationship_refs→relationship.evidence_refs; два теста сверяют точные разные назначения |

Дополнительно до review исправлены: KNOWN owner Teams Entity (сохранённый реальный output раньше давал500) и скрытая кнопка выхода при404 результата; RED→GREEN записаны в тестах/браузере. Поля произвольного stored HTML/path экранируются; источник по этим путям не читается.

Отложенный Minor: восстановление retry logout button после сетевого сбоя и последующего hidden→visible. Успех выхода не объявляется, приватное содержимое удалено; до доработки можно открыть `/ui/session` и выполнить выход. Не заявляем этот случай прошедшим.

Declined to judge: HTTPS/runtime deployment, реальные tracker links и приёмка владельцем — A6.5, остаются открыты; авторский оперативный отчёт не входил в source review, проверен его автором. Это сохранение согласованной границы, а не исключение этих обязательств из программы.
