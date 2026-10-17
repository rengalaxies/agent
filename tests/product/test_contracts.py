"""Product-boundary tests: these do not measure migration execution or quality."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from pydantic import ValidationError

from change_completion.assessment import Assessment, assess_declarations
from change_completion.models import AdapterDeclaration, ContentRef, EvidenceBinding, TransitionSpec

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)


def payload(name="service-event"):
    return json.loads((ROOT / "examples" / "product" / f"{name}.json").read_text())


def declared_setup(data):
    data["unknowns"] = []
    data["grants"] = [{"grant_id": "g1", "actor": "worker", "issued_by": "deployment-owner",
                       "component_ids": ["source", "consumer"], "actions": data["allowed_actions"],
                       "environment": "test", "starts_at": (NOW - timedelta(hours=1)).isoformat(),
                       "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                       "basis": data["before"]}]
    spec = TransitionSpec.model_validate(data)
    adapter = AdapterDeclaration(adapter_id="test-declaration", version="0.1", status="qualified",
                                 capabilities=tuple(n.capability for n in spec.needs),
                                 limits=("Test declaration, not an installed implementation",),
                                 qualification=spec.before)
    return spec, adapter


class ProductContractsTest(unittest.TestCase):
    def test_distinct_technologies_are_valid_but_not_claimed_supported(self):
        for name in ("service-event", "batch-report"):
            spec = TransitionSpec.model_validate(payload(name))
            result = assess_declarations(spec, (), at=NOW, actor="worker")
            self.assertEqual(result.coverage, "blocked")
            self.assertEqual(result.execution, "NOT_EXECUTED")
            self.assertFalse(result.effects_authorized)
            self.assertIn("MISSING_QUALIFIED_CAPABILITY", {b.code for b in result.blockers})

    def test_mandate_is_not_permission_and_qualified_is_not_execution(self):
        spec, adapter = declared_setup(payload())
        result = assess_declarations(spec, (adapter,), at=NOW, actor="worker")
        self.assertEqual(result.coverage, "declared_coverage")
        self.assertFalse(result.effects_authorized)
        self.assertEqual(result.execution, "NOT_EXECUTED")
        for updates in ({"expires_at": NOW.isoformat()}, {"starts_at": (NOW + timedelta(minutes=1)).isoformat()}, {"environment": "production"}, {"actor": "other"}):
            data = spec.model_dump(mode="json")
            data["grants"][0].update(updates)
            report = assess_declarations(TransitionSpec.model_validate(data), (adapter,), at=NOW, actor="worker")
            self.assertIn("MISSING_CURRENT_GRANT", {b.code for b in report.blockers})

    def test_read_capability_does_not_cover_patch_or_verify(self):
        spec, adapter = declared_setup(payload())
        adapter = AdapterDeclaration(**{**adapter.model_dump(), "capabilities": (spec.needs[0].capability,)})
        report = assess_declarations(spec, (adapter,), at=NOW, actor="worker")
        self.assertEqual({b.subject for b in report.blockers if b.code == "MISSING_QUALIFIED_CAPABILITY"}, {"consumer"})

    def test_planned_adapter_and_wrong_profile_do_not_cover(self):
        spec, adapter = declared_setup(payload())
        for changes in ({"status": "planned"}, {"capabilities": tuple(n.capability.model_copy(update={"profile": "different-dialect"}) for n in spec.needs)}):
            declaration = AdapterDeclaration.model_validate({**adapter.model_dump(), **changes})
            report = assess_declarations(spec, (declaration,), at=NOW, actor="worker")
            self.assertIn("MISSING_QUALIFIED_CAPABILITY", {b.code for b in report.blockers})

    def test_no_consumer_can_lose_its_requirements(self):
        data = payload()
        data["consumers"].append("source")
        with self.assertRaises(ValidationError):
            TransitionSpec.model_validate(data)

    def test_scope_and_risk_cannot_be_silently_weakened(self):
        for mutate in (
            lambda d: d["components"].append(d["components"][0]),
            lambda d: d["dependencies"][0].update(target="unlisted"),
            lambda d: d.update(criticality=1, unknowns=[]),
            lambda d: d.update(critical_risks=["irreversible money change"], criticality=2),
        ):
            data = payload()
            mutate(data)
            with self.assertRaises(ValidationError):
                TransitionSpec.model_validate(data)

    def test_unknown_and_inferred_dependencies_remain_blockers(self):
        spec, adapter = declared_setup(payload())
        data = spec.model_dump(mode="json")
        data["dependencies"][0]["certainty"] = "inferred"
        report = assess_declarations(TransitionSpec.model_validate(data), (adapter,), at=NOW, actor="worker")
        self.assertEqual(report.coverage, "blocked")
        self.assertIn("UNCONFIRMED_DEPENDENCY", {b.code for b in report.blockers})

    def test_uncertain_same_team_dependency_cannot_be_c0(self):
        data = payload()
        data.update(criticality=0, unknowns=[], impact="documentation")
        data["components"][1]["owner"] = data["components"][0]["owner"]
        data["dependencies"][0]["certainty"] = "inferred"
        with self.assertRaises(ValidationError):
            TransitionSpec.model_validate(data)

    def test_multiple_consumers_keep_distinct_expectations(self):
        data = payload("batch-report")
        spec = TransitionSpec.model_validate(data)
        self.assertEqual(len(spec.consumers), 2)
        self.assertEqual(len({r.expectation for r in spec.requirements}), 2)
        for consumer in spec.consumers:
            self.assertTrue(any(r.consumer_id == consumer for r in spec.requirements))
            self.assertTrue(any(n.component_id == consumer for n in spec.needs))

    def test_same_team_contract_change_is_not_local(self):
        data = payload()
        data.update(criticality=1, unknowns=[], impact="contract")
        for c in data["components"]:
            c["owner"] = "one-team"
        with self.assertRaises(ValidationError):
            TransitionSpec.model_validate(data)

    def test_ready_declaration_never_grants_effects(self):
        with self.assertRaises(ValidationError):
            Assessment(transition_id="x", coverage="declared_coverage", blockers=(), effects_authorized=True)

    def test_evidence_expires_and_context_or_check_change_invalidates(self):
        ref = ContentRef(uri="fixture://context", sha256="a" * 64)
        other = ContentRef(uri="fixture://context", sha256="b" * 64)
        evidence = EvidenceBinding(transition_id="t1", context=ref, check=ref, result=ref,
                                   checked_at=NOW, valid_until=NOW + timedelta(hours=1))
        self.assertTrue(evidence.matches("t1", ref, ref, NOW))
        self.assertFalse(evidence.matches("t1", ref, ref, NOW + timedelta(hours=1)))
        self.assertFalse(evidence.matches("t1", other, ref, NOW))
        self.assertFalse(evidence.matches("t1", ref, other, NOW))
        self.assertFalse(evidence.matches("t2", ref, ref, NOW))


if __name__ == "__main__":
    unittest.main()
