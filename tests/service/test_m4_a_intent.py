"""Author-written M4-A regressions, not held-out evaluation data."""
import unittest

from agent_service.intent import match_intent

OPS = [dict(id="depot-get", service="depot", method="GET", path="/parcels"),
       dict(id="depot-post", service="depot", method="POST", path="/labels"),
       dict(id="ledger-get", service="ledger", method="GET", path="/parcels")]


class M4AIntentRegressions(unittest.TestCase):
    def test_documenting_a_named_route_is_not_an_api_change(self):
        for texts in (["depot: update README", "Document GET /parcels pagination."],
                      ["depot: обновить README", "Описать GET /parcels и POST /labels."],
                      ["depot: documentation for GET /parcels and POST /labels"]):
            with self.subTest(texts=texts):
                self.assertEqual(match_intent(OPS, texts).operation_ids, [])

    def test_an_explicit_change_alongside_documentation_is_preserved(self):
        intent = match_intent(OPS, ["depot: update README; GET /parcels changes page_size from 40 to 3."])
        self.assertEqual((intent.operation_ids, intent.confidence), (["depot-get"], "explicit"))

    def test_negation_does_not_swallow_the_next_explicit_and_change_clause(self):
        intent = match_intent(OPS, ["depot: keep GET /parcels unchanged and change POST /labels response."])
        self.assertEqual((intent.operation_ids, intent.confidence), (["depot-post"], "explicit"))

    def test_a_service_mentioned_for_an_unchanged_route_cannot_claim_the_changed_route(self):
        intent = match_intent(OPS, ["ledger GET /parcels is unchanged; depot GET /parcels changes page size."])
        self.assertEqual((intent.operation_ids, intent.confidence), (["depot-get"], "explicit"))

    def test_service_scope_cannot_be_borrowed_from_an_unrelated_operation(self):
        intent = match_intent(OPS, ["depot POST /labels changes response; GET /parcels changes page size."])
        self.assertEqual((intent.operation_ids, intent.confidence), ([], "none"))
        self.assertEqual(intent.reason, "ambiguous_route")

    def test_russian_future_negation_is_not_a_positive_route_mention(self):
        intent = match_intent(OPS, ["depot GET /parcels не изменится. Обновить README."])
        self.assertEqual((intent.operation_ids, intent.confidence), ([], "none"))

    def test_literal_placeholder_like_text_is_not_an_operation_or_an_exception(self):
        intent = match_intent(OPS, ["depot: GET /parcels changes page_size 40 -> 3. Note @@999@@."])
        self.assertEqual(intent.operation_ids, ["depot-get"])

    def test_explicit_per_clause_service_targets_stay_distinct(self):
        intent = match_intent(OPS, ["depot GET /parcels changes page size; ledger GET /parcels changes fields."])
        self.assertEqual((intent.operation_ids, intent.confidence), (["depot-get", "ledger-get"], "explicit"))


if __name__ == "__main__":
    unittest.main()
