# Пакет для поиска экспертов

Черновик 27.09.2026. Даниил передаёт Антону для согласования. Ничего не опубликовано и никому не отправлено.

## Текст поста для LinkedIn (русский вариант)

Я работаю над магистерским исследованием в МФТИ: как безопасно выпускать изменения смысла данных, которые используют несколько независимых команд.

Например, признак "активный клиент" сохраняет название и тип, но производитель меняет правило расчёта. Для одной команды это допустимо, а у другой меняется смысл метрики. Обычная проверка схемы не обнаружит проблему.

Мы проектируем проверку до выпуска: сопоставляем изменение с подтверждёнными требованиями затронутых потребителей и формируем объяснимое решение - допустить, отклонить или направить на разбор. Карта доменных команд, продуктов и зависимостей помогает определить, чьи требования нужно учесть.

Ищу архитекторов данных, дата-инженеров, владельцев продуктов данных и специалистов по Data Mesh / data governance. Буду благодарен за короткий отзыв о реалистичности проблемы и/или участие в независимой оценке синтетических сценариев. Рабочие данные и доступы не нужны; формат и ожидаемую нагрузку сообщим заранее.

**Если готовы помочь, напишите в комментариях вашу роль и что вам ближе: обсудить постановку или оценить сценарии.** Можно также отметить коллегу с релевантным опытом.

## English version for Anton's international network

I am working on a master's research project at MIPT on safely releasing semantic changes to data products used by multiple independent teams.

For example, an "active customer" field keeps its name and type, but the producer changes its definition. One team can accept the change; another team's metric now means something different. Schema validation will not detect that risk.

We are designing a pre-release check against confirmed requirements of affected consumers. It produces an explainable decision: accept, reject, or request review. A map of domain teams, data products, and dependencies helps identify whose requirements apply.

I would value input from data architects, data engineers, data product owners, and Data Mesh / data governance practitioners. You could give brief feedback on whether this reflects real practice and/or independently review synthetic change scenarios. No company data or system access is needed; we will share the format and expected time commitment in advance.

**If interested, please comment with your role and whether you would prefer to discuss the problem or review scenarios.** Feel free to tag a colleague with relevant experience.

## Задание для экспертов: проект, не форма

- Перед показом сценариев собрать роль и релевантный опыт без ненужных персональных данных; сообщить предполагаемую нагрузку.
- Единица оценки: одно предложенное изменение, исходный и новый смысл/контракт, зафиксированные зависимости и применимые требования. Не показывать ответы V0, V1-ind, V2 и эталон.
- Отдельно спросить: хватает ли сведений; какое решение оправдано (ACCEPT / REJECT / NEEDS_REVIEW); какое требование или пробел в сведениях определило решение; насколько реалистичен сценарий.
- ACCEPT - все применимые подтверждённые обязательные требования соблюдены и известен полный состав обязательных потребителей. REJECT - доказано нарушение обязательного требования/общего запрета. NEEDS_REVIEW - недостаточно подтверждённых сведений, конфликт или неизвестная применимость. Это черновое правило должно быть сверено с Policy Engine перед заморозкой.
- Раздельно хранить ответы каждого эксперта и сценария; расхождения анализировать, а не заменять мнением большинства без правила разрешения.
- Цель около 10 экспертов из разных ролей; объём "80 утверждений на человека" из конспекта проверить пилотом на утомляемость. 800 ответов от 10 человек не являются 800 независимыми экспертами.
- Анкета/HTML и финальная версия сценариев создаются после методологической обратной связи и фиксации критериев. Антон согласует пост перед публикацией.
