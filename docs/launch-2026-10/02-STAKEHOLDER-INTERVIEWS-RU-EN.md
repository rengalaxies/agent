# Интервью с заинтересованными: RU / EN
Статус: DISCOVERY PLAN. Не записывать реальные имена, компании и ответы в публичный GitHub. Перед созвоном проверить исходное письмо и роль собеседника; ниже универсальные формулировки.

## Исследовательская цель
Не «понравится ли архитектура», а: как сейчас оформляют и согласуют изменение смысла data product; где происходит сбой; сколько потребителей/доменов; как обнаруживают воздействие; кто утверждает; сколько времени и операций занимает; кому принадлежит бюджет решения; при каких условиях допустим пилот. Не смешивать customer discovery с экспертной оценкой алгоритма.

## Сегменты / stakeholder map
- Data Platform Lead / Head of Data: боль в федеративном governance, стоимость интеграций, инфраструктурная безопасность; возможный economic buyer.
- Data Product Owner / Domain Lead: автономность выпуска и ответственность за нарушение потребителей; business/technical champion.
- Data Engineer / Architect: миграции, schema/semantic contracts, eventing, lineage; ежедневный исполнитель.
- Governance / Compliance / Security: регуляторные и доступные полномочия, аудит и обязательные проверки; gatekeeper.
- Analytics/ML Consumer: зависимость downstream расчётов от «того же поля с новым смыслом»; пострадавший пользователь.
- Research/academic expert: корректность новизны и контраста V1-ind/V2; НЕ обязательный коммерческий покупатель.

## План звонка 30-40 минут
0-3: согласовать цель и запись, объяснить что это discovery, а не продажа.
3-8: роль, стек, сколько domain teams/data products, с кем взаимодействует.
8-20: конкретная **последняя** история изменения смысла поля и последствия; последовательность действий, люди, инструменты, откаты, длительность, частота.
20-27: текущие workarounds: Schema Registry, catalog, ODCS, Pact/tests, review board, собственные проверки; что уже работает хорошо.
27-33: проверка сценария (без наведения): карточка изменения, карта downstream-потребителей, обоснованное ACCEPT/REJECT/NEEDS_REVIEW. Попросить критиковать, а не соглашаться.
33-38: пилотные ограничения и следующий шаг: синтетические артефакты, тестовый контракт, 1-2 эксперта, согласование доступа, безопасность.
38-40: разрешение на follow-up и интро (без давления).

## RU: открытие разговора
«Спасибо, что нашли время. Мы исследуем, как независимые команды согласуют изменения смысла метаданных продуктов данных и сохраняют совместимость с требованиями потребителей. Хотели бы сначала понять ваш реальный процесс, а затем показать концепцию. Это не презентация готовой промышленной системы. Можно ли делать заметки? Запись - только с вашего отдельного согласия».

## RU: основной список вопросов (выбирать по времени)
1. Расскажите о последнем изменении значения/формулы/временного окна поля, затронувшем другую команду. Как вы узнали о его последствиях?
2. Кто выявляет downstream-потребителей и насколько полон этот список? Где находится источник истины?
3. Какие контракты, тесты и правила уже защищают от семантических нарушений? Приведите пример, когда защита не сработала.
4. Кто вправе выпускать изменение? Что требует центрального согласования? Кто разрешает конфликт двух потребителей?
5. Как фиксируются версии требований и доказательства допуска? Можно ли восстановить решение спустя месяц?
6. Сколько похожих случаев за последние 3 месяца? Что было самым дорогим: ожидание, переделка, инцидент, согласование?
7. Как вы сейчас обрабатываете неизвестную семантику или неответившего потребителя?
8. Если бы карта показывала producer -> field -> consumers -> contract obligations, какую ошибку/неполноту вы бы ожидали увидеть?
9. Кто должен пользоваться системой ежедневно, кто утверждать внедрение и из какого бюджета? Какие критерии пилота и требования безопасности?
10. Что должно произойти, чтобы через месяц вы сказали: «Это нам не нужно»?
Probe: «Что произошло в последний раз?», «Покажите обезличенный пример», «Сколько участников?», «Что делали вместо этого?».

## EN: opening
“Thank you for taking the time. We are researching how autonomous data teams coordinate changes to the meaning of data product metadata while preserving downstream consumer requirements. I'd like to understand your actual workflow first, then show a concept. This is not a production-ready platform. May I take notes? I would only record the call with your explicit permission.”

## EN: questions
1. “Could you walk me through the most recent change to a field's meaning, calculation, or time window that affected another team?”
2. “How did you identify downstream consumers? How complete was the dependency inventory, and who owned it?”
3. “What do schema registries, data contracts, tests, lineage tools, and review processes already catch well? Where did they fail?”
4. “Who has the authority to release a change? Which decisions require central approval, and what happens when consumers disagree?”
5. “How do you version consumer requirements and preserve evidence for release decisions?”
6. “How often has this happened in the last quarter? What was the actual cost: waiting, rework, incidents, or coordination?”
7. “What happens when a consumer is unavailable or the semantics are ambiguous?”
8. “Looking at a producer-to-consumer dependency map, what is likely to be missing or misleading?”
9. “Who would use such a workflow, who would sponsor a pilot, and which security constraints would apply?”
10. “What evidence would convince you that this approach is unnecessary or inferior to your existing stack?”
Probes: “Tell me about the last time”, “Can you share a sanitized example?”, “Who made that decision?”, “How long did it take?”

## RU: завершение
«Правильно ли мы поняли: [пересказ фактов с указанием неизвестного]? Что в этом пересказе неверно? Мы подготовим короткое описание сценария и можем вернуться с прототипом на синтетических данных. Можно направить уточняющие вопросы и договориться о следующей встрече?»

## EN: closing
“Let me check that I understood your workflow correctly: [fact-based summary, including uncertainties]. What did I get wrong? We can share a short scenario and return with a synthetic-data prototype. Would a follow-up be useful?”

## Форма заметок (хранить приватно)
Interview ID / дата / роль / сегмент / согласие на запись; дословные наблюдения (evidence); текущий workflow с шагами; конкретный последний инцидент; frequency; actors; stack; кто owner и budget holder; cost (если численно подтверждён); workaround; objections; pilot constraints; jobs; цитаты с разрешением; гипотезы исследователя отдельно; next action + owner/date. Степень доказанности: observed / reported / assumption. Не сохранять PII в публичном репозитории.

## Кодирование интервью и порог следующего шага
До первых интервью зафиксировать: отдельно считать наличие проблемы, частоту, критичность, наличие budget owner, готовность к тесту и легальность данных. Положительная вежливость != спрос; «да, интересно» без реального примера/next step - слабый сигнал. После 5-8 интервью искать повторяющиеся истории внутри сегмента, а не сводить разные должности в единый процент. MVP/пилотный сценарий выбирать по частоте + цене ошибки + осуществимости доступа. Численных результатов интервью пока нет.

## Демонстрация на интервью
Первые 20 минут - никакого pitch deck. После discovery - 90-секундная схема, затем 3-минутный сценарий. Без рабочего UI показывать честно помеченный архитектурный storyboard. Не обещать автоматического определения доменов, семантики или владельцев без исходных артефактов.

## Follow-up (смысловые элементы, не отправлять автоматически)
Благодарность; 2-3 подтверждённых факта и вопрос на проверку; ограниченная концепция; конкретный next step с датой/ответственным; запрос только обезличенного примера/контракта и только при разрешении.
