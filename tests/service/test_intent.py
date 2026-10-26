"""Jira intent: which operations a task names, and how sure the text lets the service be.

Regression for the 6-r1 held-out failure (batch-6.md, "Что это значит", item 2): a task
that names only a service ("Обновить README сервиса ...", API explicitly unchanged) was
taken as a change of every operation of that service and answered USEFUL with every
consumer.
"""

import unittest

from agent_service.intent import match_intent, match_operations

OPS = [dict(id="op-list", service="ledger", method="GET", path="/ledger/entries"),
       dict(id="op-count", service="ledger", method="GET", path="/ledger/entries/count"),
       dict(id="op-other", service="billing", method="GET", path="/ledger/entries"),
       dict(id="op-solo", service="audit", method="GET", path="/audit/events")]


class IntentTest(unittest.TestCase):
    def test_service_named_with_api_explicitly_unchanged_is_not_a_change_of_its_operations(self):
        # Held-out 6-r1 F03 text with the service named.
        intent = match_intent(OPS, ["Обновить README сервиса ledger",
                                    "Описать локальный запуск и ссылку на runbook. Поведение API не меняется."])
        self.assertEqual((intent.operation_ids, intent.confidence, intent.reason),
                         ([], "none", "contract_unchanged_stated"))
        self.assertEqual(intent.services, ["ledger"])

    def test_service_named_without_any_contract_wording_is_not_enough_intent(self):
        intent = match_intent(OPS, ["ledger: ускорить локальную сборку", "Перенести сборку на новый раннер."])
        self.assertEqual((intent.operation_ids, intent.confidence, intent.reason), ([], "none", "service_only"))

    def test_contract_change_of_a_named_service_without_a_route_gives_candidates_not_an_answer(self):
        intent = match_intent(OPS, ["ledger: уменьшить размер страницы до 20", ""])
        self.assertEqual(intent.operation_ids, ["op-count", "op-list"])
        self.assertEqual((intent.confidence, intent.reason), ("candidate", "service_contract_unspecified"))

    def test_explicit_service_wide_contract_change_covers_every_operation(self):
        intent = match_intent(OPS, ["ledger: перевести все эндпоинты на курсорную пагинацию", ""])
        self.assertEqual(intent.operation_ids, ["op-count", "op-list"])
        self.assertEqual((intent.confidence, intent.reason), ("explicit", "service_wide"))

    def test_one_operation_in_the_graph_is_still_a_candidate_when_the_task_does_not_name_it(self):
        # The graph may miss routes it could not parse; a single known operation is not proof of intent.
        intent = match_intent(OPS, ["audit: убрать поле actor из ответа", ""])
        self.assertEqual((intent.operation_ids, intent.confidence, intent.reason),
                         (["op-solo"], "candidate", "service_contract_unspecified"))

    def test_route_the_text_says_does_not_change_is_not_a_target(self):
        intent = match_intent(OPS, ["ledger: GET /ledger/entries default page_size 100 -> 20",
                                    "Поведение GET /ledger/entries/count не меняется."])
        self.assertEqual((intent.operation_ids, intent.confidence), (["op-list"], "explicit"))

    def test_route_of_two_providers_without_a_named_service_stays_ambiguous(self):
        intent = match_intent(OPS, ["GET /ledger/entries: default page_size 100 -> 20", ""])
        self.assertEqual((intent.operation_ids, intent.reason), ([], "ambiguous_route"))

    def test_nothing_named_is_unclear_intent(self):
        intent = match_intent(OPS, ["Ускорить выдачу списка за день", "Отвечать меньшими страницами."])
        self.assertEqual((intent.operation_ids, intent.confidence, intent.reason), ([], "none", "no_mention"))

    def test_negation_of_one_clause_does_not_cancel_a_stated_change_in_another(self):
        intent = match_intent(OPS, ["ledger: API не меняется для старых клиентов, но удалить поле total из ответа",
                                    ""])
        self.assertEqual(intent.confidence, "candidate")

    def test_match_operations_keeps_its_two_value_shape(self):
        self.assertEqual(match_operations(OPS, ["Обновить README сервиса ledger. Поведение API не меняется."]),
                         ([], "contract_unchanged_stated"))


if __name__ == "__main__":
    unittest.main()
