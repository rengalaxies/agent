# Проверка артефактов пачки 02

[check_contracts.py](check_contracts.py) проверяет JSON Schema 2020-12, draft-шаблоны, пригодность и отбраковку искусственных structural fixtures, квоты 20/10/4/6, точную арифметику границ и локальные ссылки. Он не читает пользовательские корпуса, не вызывает ImpactMap или модель и не вычисляет собственное качество продукта.

Зависимости проекта не изменены. JSON Schema validator установлен только во временную папку `/tmp/impactmap-batch02/validator`; точная версия и Python записаны в [contract-checks.json](contract-checks.json). На чистой машине можно использовать отдельный временный venv/target. Команды из корня выбранного checkout:

```sh
python3 -m pip install --target /tmp/impactmap-batch02/validator 'jsonschema>=4.18,<5'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/impactmap-batch02/validator python3 research/evaluation/verification/check_contracts.py
```

В текущем окружении фактически использован Python `/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python` (3.13.9), а не системный python3. Путь к временному validator не добавлялся в зависимости приложения. Для точного повтора закрепить версию jsonschema из сохранённого отчёта.

Проверка schema может отвергнуть пустую аттестацию, но не установить, что имя действительно принадлежит независимому человеку. SHA в synthetic fixtures — повторённые цифры для проверки формата, никогда не версии реальных данных. Обязательные проверки человеческой независимости, provenance, полноты gold, истинности цитат и межфайловых ограничений перечислены в [annotation guide](../annotation-guide-v1.md) и выполняются в 06.

[review-v1.md](review-v1.md) содержит существенные вопросы отдельного агента и решения по ним. Прохождение проверок артефактов не является подтверждением обоснованности порогов покупателями или состоявшейся независимой оценки.
