from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "scenarios" / "evaluation"
ORACLE_PATH = ROOT / "oracles" / "evaluation.yaml"
MANIFEST_PATH = ROOT / "experiments" / "evaluation-catalog.yaml"


def semantic(
    meaning: str,
    formula: str,
    *,
    unit: str | None = None,
    scale: int | None = None,
    window: int = 30,
    identity: str = "global_user_id",
    sources: list[str] | None = None,
    purposes: list[str] | None = None,
    description: str | None = None,
) -> dict:
    payload = {
        "meaning": meaning,
        "formula": formula,
        "calculation_window_days": window,
        "identity_scope": identity,
        "allowed_sources": sources or ["transactions"],
        "purposes": purposes or ["risk_scoring"],
    }
    if description is not None:
        payload["description"] = description
    if unit is not None:
        payload["unit"] = unit
    if scale is not None:
        payload["scale"] = scale
    return payload


def obligation(
    scenario_id: str,
    consumer_id: str,
    consumer_domain: str,
    product_id: str,
    *,
    version: str = "1.0.0",
    meaning: str | None = None,
    formula: str | None = None,
    units: list[str] | None = None,
    scales: list[int] | None = None,
    min_window: int | None = None,
    identities: list[str] | None = None,
    sources: list[str] | None = None,
    purposes: list[str] | None = None,
) -> dict:
    payload = {
        "obligation_id": f"{scenario_id.lower()}-{consumer_id}",
        "obligation_version": version,
        "consumer_id": consumer_id,
        "consumer_domain": consumer_domain,
        "product_id": product_id,
    }
    optional = {
        "required_meaning": meaning,
        "required_formula": formula,
        "accepted_units": units,
        "accepted_scales": scales,
        "min_window_days": min_window,
        "accepted_identity_scopes": identities,
        "allowed_sources": sources,
        "required_purposes": purposes,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    return payload


def contract(product_id: str, owner: str, version: str, sem: dict) -> dict:
    value_field = "amount" if sem.get("unit") not in {None, "score", "count"} else "value"
    return {
        "product_id": product_id,
        "contract_version": version,
        "owner_domain": owner,
        "schema_fields": {"user_id": "string", value_field: "decimal"},
        "semantic": sem,
    }


CASES: list[dict] = []


def add_case(
    scenario_id: str,
    family_id: str,
    description: str,
    product_id: str,
    owner: str,
    old_semantic: dict,
    new_semantic: dict,
    obligations: list[dict],
    scenario_class: str,
    consumer_decisions: dict[str, str],
    rationale: str,
    template_group: str,
    migrations: list[dict] | None = None,
) -> None:
    CASES.append(
        {
            "scenario": {
                "scenario_id": scenario_id,
                "family_id": family_id,
                "split": "evaluation",
                "description": description,
                "old_contract": contract(product_id, owner, "1.4.0", old_semantic),
                "new_contract": contract(product_id, owner, "2.0.0", new_semantic),
                "obligations": obligations,
                "migrations": migrations or [],
            },
            "oracle": {
                "scenario_id": scenario_id,
                "scenario_class": scenario_class,
                "expected_decision": "REJECT" if scenario_class == "dangerous" else "ACCEPT",
                "expected_consumer_decisions": consumer_decisions,
                "rationale": rationale,
            },
            "template_group": template_group,
        }
    )


# F1: meaning and formula - 8 cases, 4 dangerous and 4 admissible.
product = "engagement_quality_index"
old = semantic(
    "Индекс подтверждённой вовлечённости",
    "weighted_count(confirmed_actions)",
    unit="score",
    scale=4,
    sources=["transactions"],
    purposes=["partner_offer", "risk_scoring"],
)

def f1_ob(sid: str, consumer: str, domain: str, meaning: str, formula: str, version: str = "1.0.0") -> dict:
    return obligation(
        sid, consumer, domain, product, version=version, meaning=meaning, formula=formula,
        min_window=30, identities=["global_user_id"], sources=["transactions", "web_events", "crm"],
        purposes=["partner_offer"] if consumer != "fintech-risk" else ["risk_scoring"],
    )

new_meaning = "Индекс подтверждённой и просмотровой вовлечённости"
new_formula = "weighted_count(confirmed_actions) + 0.2 * view_count"
add_case("M-11", "F1", "В индекс добавлены просмотры, хотя активный потребитель требует только подтверждённые действия", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": new_meaning, "formula": new_formula, "allowed_sources": ["transactions", "web_events"]}, [f1_ob("M-11", "mobility-offers", "mobility", old["meaning"], old["formula"])], "dangerous", {"mobility-offers": "REJECT"}, "Новая формула и смысл не соответствуют обязательству активного потребителя.", "meaning-views-single")
add_case("M-12", "F1", "Уточнено только документационное описание без изменения смысла и вычисления", product, "retail", {**deepcopy(old), "description": "Индекс активности"}, {**deepcopy(old), "description": "Индекс активности по подтверждённым событиям"}, [f1_ob("M-12", "mobility-offers", "mobility", old["meaning"], old["formula"])], "admissible", {"mobility-offers": "ACCEPT"}, "Типизированные смысл и формула не изменились.", "meaning-description-single")
add_case("M-13", "F1", "Формула заменена на максимум; один потребитель принимает новую версию, второй сохраняет старое требование", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": "Пиковая подтверждённая вовлечённость", "formula": "max_daily_count(confirmed_actions)"}, [f1_ob("M-13", "mobility-offers", "mobility", old["meaning"], old["formula"]), f1_ob("M-13", "fintech-risk", "fintech", "Пиковая подтверждённая вовлечённость", "max_daily_count(confirmed_actions)", "2.0.0")], "dangerous", {"mobility-offers": "REJECT", "fintech-risk": "ACCEPT"}, "Хотя Fintech принимает новую формулу, обязательство Mobility нарушено.", "meaning-conflict-multi")
add_case("M-14", "F1", "Оба активных потребителя перешли на новую формулу нормализованной вовлечённости", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": "Нормализованная подтверждённая вовлечённость", "formula": "normalized_count(confirmed_actions)"}, [f1_ob("M-14", "mobility-offers", "mobility", "Нормализованная подтверждённая вовлечённость", "normalized_count(confirmed_actions)", "2.0.0"), f1_ob("M-14", "fintech-risk", "fintech", "Нормализованная подтверждённая вовлечённость", "normalized_count(confirmed_actions)", "2.0.0")], "admissible", {"mobility-offers": "ACCEPT", "fintech-risk": "ACCEPT"}, "Новый смысл и формула совпадают с версиями обязательств обоих потребителей.", "meaning-updated-multi")
add_case("M-15", "F1", "Из формулы исключены возвраты без обновления требования потребителя", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": "Индекс вовлечённости без возвратов", "formula": "weighted_count(confirmed_actions excluding returns)"}, [f1_ob("M-15", "mobility-offers", "mobility", old["meaning"], old["formula"])], "dangerous", {"mobility-offers": "REJECT"}, "Семантика выборки изменилась, а обязательство осталось прежним.", "meaning-filter-single")
add_case("M-16", "F1", "Потребитель заранее перешёл на индекс без возвратов", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": "Индекс вовлечённости без возвратов", "formula": "weighted_count(confirmed_actions excluding returns)"}, [f1_ob("M-16", "mobility-offers", "mobility", "Индекс вовлечённости без возвратов", "weighted_count(confirmed_actions excluding returns)", "2.0.0")], "admissible", {"mobility-offers": "ACCEPT"}, "Версионированное обязательство потребителя соответствует новой семантике.", "meaning-filter-updated")
add_case("M-17", "F1", "Название смысла расширено до прогнозной активности при неизменной формуле исторического счёта", product, "retail", deepcopy(old), {**deepcopy(old), "meaning": "Прогноз будущей вовлечённости"}, [f1_ob("M-17", "mobility-offers", "mobility", old["meaning"], old["formula"])], "dangerous", {"mobility-offers": "REJECT"}, "Заявленный смысл больше не соответствует обязательству, даже при прежней формуле.", "meaning-label-single")
add_case("M-18", "F1", "Добавлено пояснение о часовом поясе без изменения типизированной семантики", product, "retail", {**deepcopy(old), "description": "Расчёт по календарным дням"}, {**deepcopy(old), "description": "Расчёт по календарным дням UTC"}, [f1_ob("M-18", "mobility-offers", "mobility", old["meaning"], old["formula"]), f1_ob("M-18", "fintech-risk", "fintech", old["meaning"], old["formula"])], "admissible", {"mobility-offers": "ACCEPT", "fintech-risk": "ACCEPT"}, "Изменилось только описание; проверяемые смысл и формула сохранены.", "meaning-description-multi")

# F2: unit and scale - 8 cases, 4 dangerous and 4 admissible.
product = "settled_amount_profile"
money = semantic("Сумма подтверждённых операций", "sum(settled_amount)", unit="EUR", scale=2, sources=["transactions"], purposes=["risk_scoring", "partner_offer"])

def f2_ob(sid: str, consumer: str, domain: str, units: list[str], scales: list[int]) -> dict:
    return obligation(sid, consumer, domain, product, formula=money["formula"], units=units, scales=scales, min_window=30, identities=["global_user_id"], sources=["transactions"], purposes=["risk_scoring"] if consumer == "fintech-risk" else ["partner_offer"])

valid_cent = [{"dimension": "unit_scale", "source": "euro_cent:0", "target": "EUR:2", "expression": "value / 100", "validated_examples": 8}]
add_case("U-11", "F2", "Евро заменены евроцентами без преобразования", product, "fintech", deepcopy(money), {**deepcopy(money), "unit": "euro_cent", "scale": 0}, [f2_ob("U-11", "retail-offers", "retail", ["EUR"], [2])], "dangerous", {"retail-offers": "REJECT"}, "Потребитель не может восстановить требуемое представление EUR:2.", "unit-missing-migration")
add_case("U-12", "F2", "Евро заменены евроцентами с проверенным преобразованием", product, "fintech", deepcopy(money), {**deepcopy(money), "unit": "euro_cent", "scale": 0}, [f2_ob("U-12", "retail-offers", "retail", ["EUR"], [2])], "admissible", {"retail-offers": "ACCEPT"}, "Проверенная миграция восстанавливает EUR:2.", "unit-valid-migration", valid_cent)
add_case("U-13", "F2", "Точность суммы снижена с пяти до двух знаков без преобразования", product, "fintech", {**deepcopy(money), "scale": 5}, deepcopy(money), [f2_ob("U-13", "risk-model", "retail", ["EUR"], [5])], "dangerous", {"risk-model": "REJECT"}, "Ожидаемый масштаб 5 не восстанавливается из нового EUR:2.", "scale-missing-migration")
add_case("U-14", "F2", "Активный потребитель напрямую принимает новый масштаб", product, "fintech", {**deepcopy(money), "scale": 5}, deepcopy(money), [f2_ob("U-14", "risk-model", "retail", ["EUR"], [2])], "admissible", {"risk-model": "ACCEPT"}, "Новый формат напрямую входит в принятое потребителем множество.", "scale-direct")
add_case("U-15", "F2", "Объявлено, но не проверено преобразование из евроцентов", product, "fintech", deepcopy(money), {**deepcopy(money), "unit": "euro_cent", "scale": 0}, [f2_ob("U-15", "retail-offers", "retail", ["EUR"], [2])], "dangerous", {"retail-offers": "REJECT"}, "Миграция без проверенных примеров не считается валидной.", "unit-unvalidated", [{"dimension": "unit_scale", "source": "euro_cent:0", "target": "EUR:2", "expression": "value / 100", "validated_examples": 0}])
add_case("U-16", "F2", "Один потребитель читает евроценты напрямую, второй использует проверенную миграцию", product, "fintech", deepcopy(money), {**deepcopy(money), "unit": "euro_cent", "scale": 0}, [f2_ob("U-16", "retail-offers", "retail", ["EUR"], [2]), f2_ob("U-16", "mobility-billing", "mobility", ["euro_cent"], [0])], "admissible", {"retail-offers": "ACCEPT", "mobility-billing": "ACCEPT"}, "Оба обязательства выполняются допустимыми способами.", "unit-mixed-multi", valid_cent)
add_case("U-17", "F2", "Миграция объявлена в неверном направлении", product, "fintech", deepcopy(money), {**deepcopy(money), "unit": "euro_cent", "scale": 0}, [f2_ob("U-17", "retail-offers", "retail", ["EUR"], [2])], "dangerous", {"retail-offers": "REJECT"}, "Преобразование EUR:2 в euro_cent:0 не восстанавливает требуемый формат из нового контракта.", "unit-wrong-direction", [{"dimension": "unit_scale", "source": "EUR:2", "target": "euro_cent:0", "expression": "value * 100", "validated_examples": 8}])
add_case("U-18", "F2", "Масштаб изменён с пяти до двух знаков с проверенным восстановлением", product, "fintech", {**deepcopy(money), "scale": 5}, deepcopy(money), [f2_ob("U-18", "risk-model", "retail", ["EUR"], [5])], "admissible", {"risk-model": "ACCEPT"}, "Проверенное преобразование восстанавливает требуемый масштаб.", "scale-valid-migration", [{"dimension": "unit_scale", "source": "EUR:2", "target": "EUR:5", "expression": "round(value, 5)", "validated_examples": 6}])

# F3: calculation window - 6 cases, 3 dangerous and 3 admissible.
product = "trip_frequency_profile"
time_base = semantic("Частота завершённых поездок", "count(completed_trip)", unit="count", scale=0, window=28, sources=["transactions"], purposes=["partner_offer", "risk_scoring"])

def f3_ob(sid: str, consumer: str, domain: str, minimum: int) -> dict:
    return obligation(sid, consumer, domain, product, formula=time_base["formula"], units=["count"], scales=[0], min_window=minimum, identities=["global_user_id"], sources=["transactions"], purposes=["risk_scoring"] if consumer == "fintech-risk" else ["partner_offer"])

add_case("T-11", "F3", "Окно сокращено с 28 до 10 дней при минимуме 28 дней", product, "mobility", deepcopy(time_base), {**deepcopy(time_base), "calculation_window_days": 10}, [f3_ob("T-11", "retail-offers", "retail", 28)], "dangerous", {"retail-offers": "REJECT"}, "Новое окно меньше минимального обязательства.", "window-short-single")
add_case("T-12", "F3", "Окно увеличено с 28 до 56 дней при минимуме 28 дней", product, "mobility", deepcopy(time_base), {**deepcopy(time_base), "calculation_window_days": 56}, [f3_ob("T-12", "retail-offers", "retail", 28)], "admissible", {"retail-offers": "ACCEPT"}, "Новое окно не ниже минимального требования.", "window-long-single")
add_case("T-13", "F3", "Окно сокращено с 84 до 21 дня; требования двух потребителей различаются", product, "mobility", {**deepcopy(time_base), "calculation_window_days": 84}, {**deepcopy(time_base), "calculation_window_days": 21}, [f3_ob("T-13", "retail-offers", "retail", 84), f3_ob("T-13", "fintech-risk", "fintech", 10)], "dangerous", {"retail-offers": "REJECT", "fintech-risk": "ACCEPT"}, "Окно подходит Fintech, но нарушает минимум Retail.", "window-conflict-multi")
add_case("T-14", "F3", "Окно увеличено с 10 до 20 дней для двух потребителей", product, "mobility", {**deepcopy(time_base), "calculation_window_days": 10}, {**deepcopy(time_base), "calculation_window_days": 20}, [f3_ob("T-14", "retail-offers", "retail", 10), f3_ob("T-14", "fintech-risk", "fintech", 20)], "admissible", {"retail-offers": "ACCEPT", "fintech-risk": "ACCEPT"}, "Окно удовлетворяет обоим минимумам.", "window-valid-multi")
add_case("T-15", "F3", "Окно сокращено до трёх дней при минимуме десять дней", product, "mobility", {**deepcopy(time_base), "calculation_window_days": 21}, {**deepcopy(time_base), "calculation_window_days": 3}, [f3_ob("T-15", "fintech-risk", "fintech", 10)], "dangerous", {"fintech-risk": "REJECT"}, "Трёхдневное окно нарушает обязательство потребителя.", "window-three-days")
add_case("T-16", "F3", "Окно увеличено с 21 до 42 дней без изменения остальных измерений", product, "mobility", {**deepcopy(time_base), "calculation_window_days": 21}, {**deepcopy(time_base), "calculation_window_days": 42}, [f3_ob("T-16", "fintech-risk", "fintech", 21)], "admissible", {"fintech-risk": "ACCEPT"}, "Монотонное ограничение минимального окна выполняется.", "window-monotonic")

# F4: identity scope - 6 cases, 3 dangerous and 3 admissible.
product = "customer_presence_profile"
identity_base = semantic("Последняя подтверждённая зона присутствия", "latest_confirmed_zone(event_time)", window=7, sources=["crm"], purposes=["partner_offer", "risk_scoring"])

def f4_ob(sid: str, consumer: str, domain: str, identities: list[str]) -> dict:
    return obligation(sid, consumer, domain, product, formula=identity_base["formula"], min_window=7, identities=identities, sources=["crm"], purposes=["risk_scoring"] if consumer == "fintech-risk" else ["partner_offer"])

add_case("I-11", "F4", "Глобальный идентификатор заменён идентификатором сессии без отображения", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "session_id"}, [f4_ob("I-11", "retail-offers", "retail", ["global_user_id"])], "dangerous", {"retail-offers": "REJECT"}, "Требуемая глобальная область идентичности не восстанавливается.", "identity-missing-map")
add_case("I-12", "F4", "Глобальный идентификатор заменён идентификатором арендатора с взаимно-однозначным отображением", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "tenant_user_id"}, [f4_ob("I-12", "retail-offers", "retail", ["global_user_id"])], "admissible", {"retail-offers": "ACCEPT"}, "Проверенное взаимно-однозначное отображение восстанавливает global_user_id.", "identity-valid-map", [{"dimension": "identity_scope", "source": "tenant_user_id", "target": "global_user_id", "expression": "tenant_identity_map_v1", "validated_examples": 12, "bijective": True}])
add_case("I-13", "F4", "Объявлено необратимое отображение из сессии в пользователя", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "session_id"}, [f4_ob("I-13", "retail-offers", "retail", ["global_user_id"])], "dangerous", {"retail-offers": "REJECT"}, "Необратимое отображение не считается валидной миграцией идентичности.", "identity-nonbijective", [{"dimension": "identity_scope", "source": "session_id", "target": "global_user_id", "expression": "latest_session_owner", "validated_examples": 20, "bijective": False}])
add_case("I-14", "F4", "Потребитель напрямую принимает новую область идентификатора арендатора", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "tenant_user_id"}, [f4_ob("I-14", "retail-offers", "retail", ["tenant_user_id"])], "admissible", {"retail-offers": "ACCEPT"}, "Новая область явно разрешена действующим обязательством.", "identity-direct")
add_case("I-15", "F4", "Миграция идентификатора объявлена в обратном направлении", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "tenant_user_id"}, [f4_ob("I-15", "fintech-risk", "fintech", ["global_user_id"])], "dangerous", {"fintech-risk": "REJECT"}, "Отображение из global_user_id в tenant_user_id не восстанавливает ожидаемую область из нового контракта.", "identity-wrong-direction", [{"dimension": "identity_scope", "source": "global_user_id", "target": "tenant_user_id", "expression": "tenant_lookup", "validated_examples": 10, "bijective": True}])
add_case("I-16", "F4", "Один потребитель принимает область арендатора напрямую, второй использует отображение", product, "mobility", deepcopy(identity_base), {**deepcopy(identity_base), "identity_scope": "tenant_user_id"}, [f4_ob("I-16", "retail-offers", "retail", ["tenant_user_id"]), f4_ob("I-16", "fintech-risk", "fintech", ["global_user_id"])], "admissible", {"retail-offers": "ACCEPT", "fintech-risk": "ACCEPT"}, "Оба потребителя получают допустимую для них область идентичности.", "identity-mixed-multi", [{"dimension": "identity_scope", "source": "tenant_user_id", "target": "global_user_id", "expression": "tenant_identity_map_v1", "validated_examples": 12, "bijective": True}])

# F5: lineage - 6 cases, 3 dangerous and 3 admissible.
product = "offer_eligibility_signal"
lineage_base = semantic("Признак допустимости предложения", "eligibility_score(events)", unit="score", scale=4, sources=["crm"], purposes=["partner_offer", "risk_scoring"])

def f5_ob(sid: str, consumer: str, domain: str, sources: list[str]) -> dict:
    return obligation(sid, consumer, domain, product, formula=lineage_base["formula"], min_window=30, identities=["global_user_id"], sources=sources, purposes=["risk_scoring"] if consumer == "fintech-risk" else ["partner_offer"])

add_case("L-11", "F5", "К CRM добавлен неразрешённый рекламный источник", product, "retail", deepcopy(lineage_base), {**deepcopy(lineage_base), "allowed_sources": ["crm", "social_ads"]}, [f5_ob("L-11", "mobility-offers", "mobility", ["crm", "web_events"])], "dangerous", {"mobility-offers": "REJECT"}, "Источник social_ads отсутствует в разрешённом множестве потребителя.", "lineage-forbidden-single")
add_case("L-12", "F5", "К CRM добавлен разрешённый web-источник", product, "retail", deepcopy(lineage_base), {**deepcopy(lineage_base), "allowed_sources": ["crm", "web_events"]}, [f5_ob("L-12", "mobility-offers", "mobility", ["crm", "web_events"])], "admissible", {"mobility-offers": "ACCEPT"}, "Все источники входят в разрешённое множество.", "lineage-approved-single")
add_case("L-13", "F5", "Добавлены разрешённый loyalty-источник и запрещённый внешний профиль", product, "retail", deepcopy(lineage_base), {**deepcopy(lineage_base), "allowed_sources": ["crm", "loyalty", "external_profile"]}, [f5_ob("L-13", "mobility-offers", "mobility", ["crm", "loyalty"])], "dangerous", {"mobility-offers": "REJECT"}, "Один запрещённый источник нарушает обязательство независимо от разрешённого источника.", "lineage-mixed-single")
add_case("L-14", "F5", "Набор источников сужен до loyalty при неизменной формуле", product, "retail", {**deepcopy(lineage_base), "allowed_sources": ["crm", "loyalty"]}, {**deepcopy(lineage_base), "allowed_sources": ["loyalty"]}, [f5_ob("L-14", "mobility-offers", "mobility", ["crm", "loyalty"])], "admissible", {"mobility-offers": "ACCEPT"}, "Оставшийся источник разрешён потребителем.", "lineage-narrow")
add_case("L-15", "F5", "Источник web_events заменён брокером местоположения", product, "retail", {**deepcopy(lineage_base), "allowed_sources": ["web_events"]}, {**deepcopy(lineage_base), "allowed_sources": ["location_broker"]}, [f5_ob("L-15", "fintech-risk", "fintech", ["web_events", "crm"])], "dangerous", {"fintech-risk": "REJECT"}, "Новый источник не входит в разрешённое множество Fintech.", "lineage-replacement")
add_case("L-16", "F5", "Два потребителя явно разрешают новый источник телеметрии", product, "retail", deepcopy(lineage_base), {**deepcopy(lineage_base), "allowed_sources": ["crm", "telemetry"]}, [f5_ob("L-16", "mobility-offers", "mobility", ["crm", "telemetry"]), f5_ob("L-16", "fintech-risk", "fintech", ["crm", "telemetry"])], "admissible", {"mobility-offers": "ACCEPT", "fintech-risk": "ACCEPT"}, "Новый источник входит в обязательства обоих активных потребителей.", "lineage-consumer-update-multi")

# F6: purposes - 6 cases, 3 dangerous and 3 admissible.
product = "customer_risk_context"
purpose_base = semantic("Контекст риска клиента", "risk_context(events)", unit="score", scale=4, sources=["transactions"], purposes=["risk_scoring", "retention"])

def f6_ob(sid: str, consumer: str, domain: str, purposes: list[str]) -> dict:
    return obligation(sid, consumer, domain, product, formula=purpose_base["formula"], min_window=30, identities=["global_user_id"], sources=["transactions"], purposes=purposes)

add_case("P-11", "F6", "Из контракта удалена цель risk_scoring", product, "fintech", deepcopy(purpose_base), {**deepcopy(purpose_base), "purposes": ["retention"]}, [f6_ob("P-11", "fintech-risk", "fintech", ["risk_scoring"])], "dangerous", {"fintech-risk": "REJECT"}, "Обязательная цель risk_scoring отсутствует в новой версии.", "purpose-remove-risk")
add_case("P-12", "F6", "Добавлена цель partner_offer при сохранении risk_scoring", product, "fintech", deepcopy(purpose_base), {**deepcopy(purpose_base), "purposes": ["risk_scoring", "retention", "partner_offer"]}, [f6_ob("P-12", "fintech-risk", "fintech", ["risk_scoring"])], "admissible", {"fintech-risk": "ACCEPT"}, "Обязательная цель сохранена.", "purpose-add")
add_case("P-13", "F6", "Сохранён risk_scoring, но удалена обязательная для второго потребителя fraud_prevention", product, "fintech", {**deepcopy(purpose_base), "purposes": ["risk_scoring", "fraud_prevention"]}, {**deepcopy(purpose_base), "purposes": ["risk_scoring"]}, [f6_ob("P-13", "fintech-risk", "fintech", ["risk_scoring"]), f6_ob("P-13", "retail-fraud", "retail", ["fraud_prevention"])], "dangerous", {"fintech-risk": "ACCEPT", "retail-fraud": "REJECT"}, "Глобальная политика сохраняется, но обязательство Retail нарушено.", "purpose-conflict-multi")
add_case("P-14", "F6", "Удалена необязательная цель retention при сохранении требований двух потребителей", product, "fintech", deepcopy(purpose_base), {**deepcopy(purpose_base), "purposes": ["risk_scoring"]}, [f6_ob("P-14", "fintech-risk", "fintech", ["risk_scoring"]), f6_ob("P-14", "retail-audit", "retail", ["risk_scoring"])], "admissible", {"fintech-risk": "ACCEPT", "retail-audit": "ACCEPT"}, "Все обязательные цели остаются в контракте.", "purpose-remove-optional")
add_case("P-15", "F6", "Цель retention заменена acquisition без обновления обязательства", product, "fintech", deepcopy(purpose_base), {**deepcopy(purpose_base), "purposes": ["risk_scoring", "acquisition"]}, [f6_ob("P-15", "retail-retention", "retail", ["retention"])], "dangerous", {"retail-retention": "REJECT"}, "Новая версия не содержит обязательную цель retention.", "purpose-replace")
add_case("P-16", "F6", "Добавлена цель audit при сохранении risk_scoring и retention", product, "fintech", deepcopy(purpose_base), {**deepcopy(purpose_base), "purposes": ["risk_scoring", "retention", "audit"]}, [f6_ob("P-16", "fintech-risk", "fintech", ["risk_scoring"]), f6_ob("P-16", "retail-retention", "retail", ["retention"])], "admissible", {"fintech-risk": "ACCEPT", "retail-retention": "ACCEPT"}, "Расширение не удаляет ни одной обязательной цели.", "purpose-add-multi")


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def cluster_id_for(scenario_id: str, family_id: str) -> str:
    number = int(scenario_id.split("-")[1])
    pair_number = ((number - 11) // 2) + 1
    return f"eval-{family_id.lower()}-{pair_number:02d}"


def main() -> None:
    if len(CASES) != 40:
        raise RuntimeError(f"expected 40 cases, got {len(CASES)}")
    scenario_ids = [item["scenario"]["scenario_id"] for item in CASES]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise RuntimeError("duplicate evaluation scenario ids")
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    for path in SCENARIO_DIR.glob("*.yaml"):
        path.unlink()
    for item in CASES:
        write_yaml(SCENARIO_DIR / f"{item['scenario']['scenario_id']}.yaml", item["scenario"])
    write_yaml(
        ORACLE_PATH,
        {
            "catalog_id": "evaluation-oracle-0.3.0",
            "split": "evaluation",
            "labels": [item["oracle"] for item in CASES],
        },
    )
    manifest = {
            "catalog_id": "evaluation-catalog-0.3.0",
            "protocol_version": "0.3.0",
            "scenario_count": 40,
            "dangerous_count": 20,
            "admissible_count": 20,
            "family_distribution": {"F1": 8, "F2": 8, "F3": 6, "F4": 6, "F5": 6, "F6": 6},
            "generation_seed": 20260916,
            "group_split_rule": "template groups are evaluation-only and have no development counterpart",
            "oracle_exposed_to_validators": False,
            "scoring_only_metadata": True,
            "main_e3_executed": False,
            "scenario_catalog_sha256": catalog_hash(SCENARIO_DIR),
            "oracle_sha256": file_hash(ORACLE_PATH),
            "baseline_policy_sha256": file_hash(ROOT / "policies" / "v1-ind.yaml"),
            "generator_sha256": file_hash(Path(__file__)),
            "scenarios": [
                {
                    "scenario_id": item["scenario"]["scenario_id"],
                    "family_id": item["scenario"]["family_id"],
                    "cluster_id": cluster_id_for(
                        item["scenario"]["scenario_id"],
                        item["scenario"]["family_id"],
                    ),
                    "template_group": item["template_group"],
                    "consumer_count": len(item["scenario"]["obligations"]),
                }
                for item in CASES
            ],
        }
    write_yaml(MANIFEST_PATH, manifest)


if __name__ == "__main__":
    main()
