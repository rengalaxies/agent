# Infrastructure

Историческая инфраструктурная гипотеза предполагала Kafka KRaft, Schema Registry и PostgreSQL. Эти компоненты не являются обязательным стеком нового продукта. Фактический development deployment находится в `deploy/p1`; optional PostgreSQL audit - в `services/audit_pg.py`. Текущие границы on-premise поставки и подключаемых адаптеров: [продуктовый документ](../docs/product-rebuild-2026-10-16.md). Production-поставка еще не квалифицирована.
