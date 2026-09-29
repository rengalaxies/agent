# Переносимый стенд E4

Три доменных процесса, отдельные SQLite-хранилища, подписанные события и устойчивое разрешение выпуска. Подробные результаты, команды и границы: [отчёт пакета 2](../docs/package-2-distributed-2026-09-29.md).

```bash
pip install -r stand/requirements.lock
pip install --no-deps -e .
make e4-fast
make e4-standard
make e4-recovery
PYTHONPATH=src python stand/demo.py --state .runtime/demo --run-id demo-1
```

В `run_e4.py` используются только самостоятельные synthetic E4 fixtures. Evaluation-каталог и scoring labels не читаются. `demo.py` сохраняет состояние; тестовые прогоны используют временное состояние и удаляют его после завершения. Полные архивные результаты проверяются `PYTHONPATH=src python stand/verify_archive.py`.

Dockerfile предназначен для последующей сборки на Linux; в текущем окружении образ не собирался. Для Cloud.ru ещё нужны инфраструктура, защищённый канал, секреты, наблюдаемость и отдельный облачный manifest. Публичные порты штатно не открываются.
