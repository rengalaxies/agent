# Пакет для поиска экспертов

Черновик 27.09.2026. Даниил передаёт Антону для согласования. Ничего не опубликовано и никому не отправлено.

## Текст поста для LinkedIn (русский вариант)

Я работаю над магистерским исследованием в МФТИ о том, как безопасно выпускать изменения смысла данных, которыми пользуются несколько независимых команд.

Представьте продукт данных с признаком "активный клиент". Его тип и название не меняются, но производитель меняет правило расчёта. Для одной команды новая версия допустима, для другой ломает отчёт. Проверка схемы такого риска не увидит.

Мы проектируем механизм, который до выпуска сверяет изменение с подтверждёнными требованиями затронутых потребителей и объясняет решение: допустить, отклонить или направить на разбор. В архитектуру входит базовая карта команд, продуктов данных и зависимостей с доменным владением требованиями. Сейчас мы проверяем качество выявления опасных изменений и ищем людей, которые помогут сделать исследование честнее.

Ищем архитекторов данных, дата-инженеров, владельцев продуктов данных и специалистов по Data Mesh / data governance. Будет полезна помощь в одном или обоих форматах:

1. Короткий отзыв: реалистична ли проблема и понятна ли постановка?
2. Независимая оценка учебных сценариев изменений по краткой инструкции: ACCEPT, REJECT или NEEDS_REVIEW с указанием основания.

Сценарии синтетические, реальные данные и доступы не требуются. Объём и время анкеты сообщим заранее; можно участвовать только в первом формате. Если вам интересно, напишите мне в личные сообщения или отметьте коллегу, чей опыт подходит.

## English version for Anton's international network

I am working on a master's research project at MIPT about releasing semantic changes to data products used by multiple independent teams.

Imagine a data product with an "active customer" field. Its name and type stay the same, but the producer changes how it is calculated. The change is acceptable for one consumer and breaks a report for another. Schema validation alone will not catch this.

We are designing a pre-release check against confirmed, versioned requirements of affected consumers. It produces an explainable ACCEPT, REJECT, or NEEDS_REVIEW decision. A basic map of domain teams, data products, dependencies, and ownership supplies the context. The research focuses on detecting harmful semantic changes, while tracking false blocks and cases needing review.

We would value input from data architects, data engineers, data product owners, and people working with Data Mesh or data governance. There are two ways to help:

1. Give brief feedback on whether the problem and scenarios reflect real practice.
2. Independently label synthetic change scenarios using a short rubric, with a reason for each decision.

No company data or system access is needed. We will share the expected time commitment before participation. You can choose either activity. Please message me if you are interested, or tag a colleague with relevant experience.

## Задание для экспертов: проект, не форма

- Перед показом сценариев собрать роль и релевантный опыт без ненужных персональных данных; сообщить предполагаемую нагрузку.
- Единица оценки: одно предложенное изменение, исходный и новый смысл/контракт, зафиксированные зависимости и применимые требования. Не показывать ответы V0, V1-ind, V2 и эталон.
- Отдельно спросить: хватает ли сведений; какое решение оправдано (ACCEPT / REJECT / NEEDS_REVIEW); какое требование или пробел в сведениях определило решение; насколько реалистичен сценарий.
- ACCEPT - все применимые подтверждённые обязательные требования соблюдены и известен полный состав обязательных потребителей. REJECT - доказано нарушение обязательного требования/общего запрета. NEEDS_REVIEW - недостаточно подтверждённых сведений, конфликт или неизвестная применимость. Это черновое правило должно быть сверено с Policy Engine перед заморозкой.
- Раздельно хранить ответы каждого эксперта и сценария; расхождения анализировать, а не заменять мнением большинства без правила разрешения.
- Цель около 10 экспертов из разных ролей; объём "80 утверждений на человека" из конспекта проверить пилотом на утомляемость. 800 ответов от 10 человек не являются 800 независимыми экспертами.
- Анкета/HTML и финальная версия сценариев создаются после методологической обратной связи и фиксации критериев. Антон согласует пост перед публикацией.
