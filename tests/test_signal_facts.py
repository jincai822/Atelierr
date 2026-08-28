from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "atelier"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _paths  # noqa: E402
import signal_facts  # noqa: E402


def observation(
    metric_id: str,
    definition_id: str,
    value: int | float,
    *,
    basis: str = "quarter",
    kind: str = "reported",
    verification: str = "primary-deterministic",
    observation_date: str | None = None,
) -> dict:
    result = {
        "metric_id": metric_id,
        "definition_id": definition_id,
        "value": value,
        "unit": "USD",
        "scale": 1_000_000,
        "period_basis": basis,
        "scope": "consolidated",
        "kind": kind,
        "verification": verification,
    }
    if observation_date is not None:
        result["observation_date"] = observation_date
    return result


def record(
    entity: str,
    document_id: str,
    observations: list[dict],
    *,
    period_start: str = "2026-01-01",
    period_end: str = "2026-03-31",
    fiscal_period: str = "Q1 2026",
    available_at: str = "2026-04-29T20:00:00Z",
    supersedes: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "entity": {"id": entity, "ticker": entity},
        "event": {
            "kind": "earnings",
            "fiscal_period": fiscal_period,
            "period_start": period_start,
            "period_end": period_end,
            "reported_at": "2026-04-29T20:00:00Z",
        },
        "source": {
            "type": "investor-relations",
            "url": f"https://example.test/{document_id}",
            "accession_or_document_id": document_id,
            "available_at": available_at,
            "retrieved_at": "2026-07-30T07:00:00Z",
        },
        "observations": observations,
        "supersedes": supersedes or [],
    }


class SignalFactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "_meta").mkdir()
        (self.root / "_meta" / "signal_facts.toml").write_text(
            """
schema_version = 1
ledger_dir = "finance/facts"
cache_dir = "cache/signal-facts"

[profiles.finance]
entities = ["ALPHA", "BETA"]
latest_periods = 2
max_age_days = 130

[[profiles.finance.metrics]]
metric_id = "operating_cash_flow"
definition_id = "gaap_operating_cash_flow"
required = true

[[profiles.finance.metrics]]
metric_id = "cash_ppe_purchases"
definition_id = "gross_cash_ppe_purchases"
required = true

[[profiles.finance.metrics]]
metric_id = "cash_ppe_proceeds_and_incentives"
definition_id = "explicit_cash_offsets"

[[profiles.finance.metrics]]
metric_id = "finance_lease_principal"
definition_id = "cash_finance_lease_principal"

[[profiles.finance.metrics]]
metric_id = "free_cash_flow"
definition_id = "company_reported"

[[profiles.finance.metrics]]
metric_id = "free_cash_flow"
definition_id = "canonical_cash_capex_fcf_v1"

[[profiles.finance.metrics]]
metric_id = "free_cash_flow"
definition_id = "lease_adjusted_fcf_v1"

[[profiles.finance.signals]]
signal_id = "NEGATIVE_FCF_BREADTH"
kind = "distinct_entities_below"
metric_id = "free_cash_flow"
definition_id = "canonical_cash_capex_fcf_v1"
period_basis = "quarter"
threshold = 0
required_count = 2
""".lstrip(),
            encoding="utf-8",
        )
        self.env_patch = patch.dict(os.environ, {"OV": str(self.root)})
        self.env_patch.start()
        _paths.vault_root.cache_clear()
        self.config = signal_facts.load_config()

    def tearDown(self) -> None:
        _paths.vault_root.cache_clear()
        self.env_patch.stop()
        self.temp.cleanup()

    def alpha_record(self) -> dict:
        return record(
            "ALPHA",
            "alpha-q1-2026",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", 120),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    150,
                ),
                observation(
                    "cash_ppe_proceeds_and_incentives",
                    "explicit_cash_offsets",
                    5,
                ),
                observation(
                    "free_cash_flow",
                    "company_reported",
                    40,
                    basis="ttm",
                    verification="primary-extracted",
                ),
            ],
        )

    def test_quarter_and_ttm_are_kept_separate(self) -> None:
        signal_facts.ingest_record(self.config, self.alpha_record())
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        event = bundle["entities"][0]["events"][0]
        keyed = {
            (
                item["metric_id"],
                item["definition_id"],
                item["period_basis"],
            ): item
            for item in event["observations"]
        }
        canonical = keyed[("free_cash_flow", "canonical_cash_capex_fcf_v1", "quarter")]
        reported = keyed[("free_cash_flow", "company_reported", "ttm")]
        self.assertEqual(canonical["value"], -25_000_000)
        self.assertEqual(reported["value"], 40_000_000)
        self.assertEqual(bundle["signals"][0]["state"], "unknown")
        self.assertEqual(bundle["signals"][0]["reading"], "1/2")

    def test_lease_adjusted_and_company_reported_remain_distinct(self) -> None:
        candidate = record(
            "BETA",
            "beta-q1-2026",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", 100),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    70,
                ),
                observation(
                    "finance_lease_principal",
                    "cash_finance_lease_principal",
                    10,
                ),
                observation("free_cash_flow", "company_reported", 30),
            ],
        )
        signal_facts.ingest_record(self.config, candidate)
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        event = bundle["entities"][1]["events"][0]
        values = {
            item["definition_id"]: item["value"]
            for item in event["observations"]
            if item["metric_id"] == "free_cash_flow"
        }
        self.assertEqual(values["company_reported"], 30_000_000)
        self.assertEqual(values["canonical_cash_capex_fcf_v1"], 30_000_000)
        self.assertEqual(values["lease_adjusted_fcf_v1"], 20_000_000)

    def test_cash_flow_derivation_rejects_mixed_units(self) -> None:
        candidate = self.alpha_record()
        candidate["observations"][1]["unit"] = "EUR"
        signal_facts.ingest_record(self.config, candidate)
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError, "cannot combine mixed units"
        ):
            signal_facts.build_bundle(
                self.config,
                profile_name="finance",
                as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )

    def test_cash_flow_operands_require_positive_magnitudes(self) -> None:
        magnitude_metrics = (
            ("cash_ppe_purchases", "gross_cash_ppe_purchases"),
            ("cash_ppe_purchases_net", "net_cash_ppe_purchases_v1"),
            (
                "cash_ppe_proceeds_and_incentives",
                "explicit_cash_offsets",
            ),
            ("finance_lease_principal", "cash_finance_lease_principal"),
        )
        for metric_id, definition_id in magnitude_metrics:
            for invalid_value in (-1, 0):
                with self.subTest(
                    metric_id=metric_id,
                    definition_id=definition_id,
                    value=invalid_value,
                ):
                    candidate = record(
                        "ALPHA",
                        f"invalid-{metric_id}-{invalid_value}",
                        [
                            observation(
                                metric_id,
                                definition_id,
                                invalid_value,
                            )
                        ],
                    )
                    with self.assertRaisesRegex(
                        signal_facts.SignalFactsError,
                        "must be a positive magnitude",
                    ):
                        signal_facts.normalize_record(
                            candidate, require_record_id=False
                        )

    def test_ocf_and_company_reported_fcf_allow_signed_values(self) -> None:
        candidate = record(
            "ALPHA",
            "signed-cash-flow",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", -5),
                observation("cash_ppe_purchases", "gross_cash_ppe_purchases", 1),
                observation("free_cash_flow", "company_reported", -6),
            ],
        )
        signal_facts.ingest_record(self.config, candidate)
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        values = {
            item["definition_id"]: item["value"]
            for item in bundle["entities"][0]["events"][0]["observations"]
            if item["metric_id"] in {"operating_cash_flow", "free_cash_flow"}
        }
        self.assertEqual(values["gaap_operating_cash_flow"], -5_000_000)
        self.assertEqual(values["company_reported"], -6_000_000)
        self.assertEqual(values["canonical_cash_capex_fcf_v1"], -6_000_000)

    def test_point_in_time_dates_remain_distinct_in_bundle(self) -> None:
        candidate = record(
            "ALPHA",
            "dated-point-in-time-facts",
            [
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    10,
                    basis="point_in_time",
                    observation_date="2026-01-31",
                ),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    20,
                    basis="point_in_time",
                    observation_date="2026-03-31",
                ),
            ],
        )
        signal_facts.ingest_record(self.config, candidate)
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        observations = [
            item
            for item in bundle["entities"][0]["events"][0]["observations"]
            if item["period_basis"] == "point_in_time"
        ]
        self.assertEqual(bundle["conflicts"], [])
        self.assertEqual(
            [item["observation_date"] for item in observations],
            ["2026-01-31", "2026-03-31"],
        )
        self.assertEqual(
            [item["value"] for item in observations],
            [10_000_000, 20_000_000],
        )
        rendered = signal_facts.render_markdown(bundle)
        self.assertIn("2026-01-31", rendered)
        self.assertIn("2026-03-31", rendered)

    def test_non_point_in_time_observation_date_is_rejected(self) -> None:
        candidate = record(
            "ALPHA",
            "invalid-quarterly-observation-date",
            [
                observation(
                    "operating_cash_flow",
                    "gaap_operating_cash_flow",
                    10,
                    observation_date="2026-03-31",
                )
            ],
        )
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "observation_date is only allowed for point_in_time",
        ):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_point_in_time_observation_date_defaults_to_period_end(self) -> None:
        for period_start in ("2026-01-01", "2026-03-31"):
            with self.subTest(period_start=period_start):
                candidate = record(
                    "ALPHA",
                    f"implicit-point-in-time-date-{period_start}",
                    [
                        observation(
                            "cash_ppe_purchases",
                            "gross_cash_ppe_purchases",
                            10,
                            basis="point_in_time",
                        )
                    ],
                    period_start=period_start,
                    period_end="2026-03-31",
                )
                normalized = signal_facts.normalize_record(
                    candidate, require_record_id=False
                )
                self.assertEqual(
                    normalized["observations"][0]["observation_date"],
                    "2026-03-31",
                )

    def test_ingest_is_idempotent_and_corrections_supersede(self) -> None:
        candidate = self.alpha_record()
        first = signal_facts.ingest_record(self.config, candidate)
        second = signal_facts.ingest_record(self.config, candidate)
        self.assertEqual(first["status"], "written")
        self.assertEqual(second["status"], "unchanged")

        corrected = self.alpha_record()
        corrected["observations"][0]["value"] = 121
        corrected["supersedes"] = [first["record_id"]]
        correction = signal_facts.ingest_record(self.config, corrected)
        self.assertEqual(correction["status"], "written")
        loaded = signal_facts.load_ledger(self.config.ledger_dir)
        active = signal_facts.active_records(
            loaded.records,
            datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [item["record_id"] for item in active], [correction["record_id"]]
        )

    def test_historical_as_of_keeps_pre_correction_record(self) -> None:
        first = signal_facts.ingest_record(self.config, self.alpha_record())
        correction_record = self.alpha_record()
        correction_record["observations"][0]["value"] = 121
        correction_record["source"]["available_at"] = "2026-06-01T12:00:00Z"
        correction_record["supersedes"] = [first["record_id"]]
        correction = signal_facts.ingest_record(self.config, correction_record)
        loaded = signal_facts.load_ledger(self.config.ledger_dir)

        before_correction = signal_facts.active_records(
            loaded.records, datetime(2026, 5, 1, tzinfo=timezone.utc)
        )
        after_correction = signal_facts.active_records(
            loaded.records, datetime(2026, 6, 2, tzinfo=timezone.utc)
        )

        self.assertEqual(
            [item["record_id"] for item in before_correction],
            [first["record_id"]],
        )
        self.assertEqual(
            [item["record_id"] for item in after_correction],
            [correction["record_id"]],
        )

    def test_source_availability_cannot_precede_event_report(self) -> None:
        candidate = self.alpha_record()
        candidate["source"]["available_at"] = "2026-04-29T19:59:59Z"
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "source.available_at cannot precede event.reported_at",
        ):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_new_record_requires_source_availability(self) -> None:
        candidate = self.alpha_record()
        del candidate["source"]["available_at"]
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "source.available_at is required for new records",
        ):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_legacy_record_defaults_availability_to_event_report(self) -> None:
        legacy = self.alpha_record()
        del legacy["source"]["available_at"]
        legacy["record_id"] = signal_facts.compute_record_id(legacy)
        normalized = signal_facts.normalize_record(legacy, require_record_id=True)
        self.assertEqual(
            signal_facts.source_available_at(normalized),
            datetime(2026, 4, 29, 20, tzinfo=timezone.utc),
        )

    def test_correction_cannot_supersede_unrelated_source(self) -> None:
        first = signal_facts.ingest_record(self.config, self.alpha_record())
        unrelated = record(
            "BETA",
            "beta-q1-2026",
            [observation("operating_cash_flow", "gaap_operating_cash_flow", 80)],
            supersedes=[first["record_id"]],
        )
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError, "same entity, period, and source"
        ):
            signal_facts.ingest_record(self.config, unrelated)

    def test_three_revision_correction_chain_supersedes_active_tip(self) -> None:
        first = signal_facts.ingest_record(self.config, self.alpha_record())
        second_record = self.alpha_record()
        second_record["observations"][0]["value"] = 121
        second_record["supersedes"] = [first["record_id"]]
        second = signal_facts.ingest_record(self.config, second_record)

        third_record = self.alpha_record()
        third_record["observations"][0]["value"] = 122
        third_record["supersedes"] = [second["record_id"]]
        third = signal_facts.ingest_record(self.config, third_record)

        loaded = signal_facts.load_ledger(self.config.ledger_dir)
        active = signal_facts.active_records(
            loaded.records,
            datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual([item["record_id"] for item in active], [third["record_id"]])

    def test_conflicting_primary_sources_make_signal_unknown(self) -> None:
        first = record(
            "ALPHA",
            "source-a",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", 100),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    120,
                ),
            ],
        )
        second = record(
            "ALPHA",
            "source-b",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", 101),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    120,
                ),
            ],
        )
        signal_facts.ingest_record(self.config, first)
        signal_facts.ingest_record(self.config, second)
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(len(bundle["conflicts"]), 1)
        self.assertEqual(bundle["signals"][0]["state"], "unknown")

    def test_candidate_source_does_not_poison_verified_fact(self) -> None:
        verified = record(
            "ALPHA",
            "verified-source",
            [
                observation("operating_cash_flow", "gaap_operating_cash_flow", 100),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    120,
                ),
            ],
        )
        candidate = record(
            "ALPHA",
            "candidate-source",
            [
                observation(
                    "operating_cash_flow",
                    "gaap_operating_cash_flow",
                    100,
                    verification="candidate",
                ),
                observation(
                    "cash_ppe_purchases",
                    "gross_cash_ppe_purchases",
                    120,
                    verification="candidate",
                ),
            ],
        )
        candidate["source"]["type"] = "secondary"
        signal_facts.ingest_record(self.config, verified)
        signal_facts.ingest_record(self.config, candidate)
        loaded = signal_facts.load_ledger(self.config.ledger_dir)
        facts, conflicts = signal_facts.resolve_facts(loaded.records)
        ocf = next(fact for fact in facts if fact["metric_id"] == "operating_cash_flow")
        self.assertEqual(ocf["verification"], "primary-deterministic")
        self.assertEqual(conflicts, [])

    def test_two_negative_entities_light_the_signal(self) -> None:
        signal_facts.ingest_record(self.config, self.alpha_record())
        signal_facts.ingest_record(
            self.config,
            record(
                "BETA",
                "beta-negative-q1",
                [
                    observation("operating_cash_flow", "gaap_operating_cash_flow", 50),
                    observation(
                        "cash_ppe_purchases",
                        "gross_cash_ppe_purchases",
                        80,
                    ),
                ],
            ),
        )
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(bundle["signals"][0]["state"], "lit")
        self.assertEqual(bundle["signals"][0]["reading"], "2/2")
        self.assertEqual(bundle["signals"][0]["scope"], "consolidated")

    def test_schema_rejects_persisted_derived_observation(self) -> None:
        candidate = record(
            "ALPHA",
            "invalid-derived",
            [
                observation(
                    "free_cash_flow",
                    "canonical_cash_capex_fcf_v1",
                    -1,
                    kind="derived",
                )
            ],
        )
        with self.assertRaisesRegex(signal_facts.SignalFactsError, "kind unsupported"):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_secondary_source_cannot_claim_primary_verification(self) -> None:
        candidate = self.alpha_record()
        candidate["source"]["type"] = "secondary"
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "secondary sources cannot use a primary verification state",
        ):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_non_earnings_event_kind_is_rejected(self) -> None:
        candidate = self.alpha_record()
        candidate["event"]["kind"] = "guidance"
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "event.kind unsupported in the current ledger",
        ):
            signal_facts.normalize_record(candidate, require_record_id=False)

    def test_bundle_is_deterministic_for_fixed_as_of(self) -> None:
        signal_facts.ingest_record(self.config, self.alpha_record())
        as_of = datetime(2026, 7, 30, tzinfo=timezone.utc)
        first = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=as_of,
        )
        second = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=as_of,
        )
        self.assertEqual(
            signal_facts.canonical_json(first),
            signal_facts.canonical_json(second),
        )

    def test_markdown_bundle_is_source_linked_with_formula_provenance(self) -> None:
        result = signal_facts.ingest_record(self.config, self.alpha_record())
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        rendered = signal_facts.render_markdown(bundle)
        self.assertIn("https://example.test/alpha-q1-2026", rendered)
        self.assertIn(result["record_id"], rendered)
        self.assertIn("canonical_cash_capex_fcf_v1", rendered)

    def test_missing_required_metric_creates_retrieval_gap(self) -> None:
        signal_facts.ingest_record(
            self.config,
            record(
                "BETA",
                "beta-incomplete-q1",
                [observation("operating_cash_flow", "gaap_operating_cash_flow", 80)],
            ),
        )
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(bundle["retrieval_required"])
        self.assertTrue(
            any(
                gap.get("entity_id") == "BETA"
                and gap.get("metric_id") == "cash_ppe_purchases"
                and gap["reason"] == "required_metric_missing_for_latest_event"
                for gap in bundle["gaps"]
            )
        )

    def test_cached_bundle_stays_under_requested_budget(self) -> None:
        signal_facts.ingest_record(self.config, self.alpha_record())
        bundle = signal_facts.build_bundle(
            self.config,
            profile_name="finance",
            as_of=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )
        compact = signal_facts.compact_bundle(bundle, 24 * 1024)
        encoded = (
            json.dumps(
                compact,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        markdown = signal_facts.render_markdown(compact).encode("utf-8")
        self.assertLessEqual(len(encoded), 24 * 1024)
        self.assertLessEqual(len(markdown), 24 * 1024)

    def test_historical_projection_cannot_replace_latest_cache(self) -> None:
        args = type(
            "Args",
            (),
            {
                "config": None,
                "profile": "finance",
                "as_of": "2026-01-01",
                "format": "json",
                "cache": True,
                "max_bytes": 24 * 1024,
            },
        )()
        with self.assertRaisesRegex(
            signal_facts.SignalFactsError,
            "historical projections must not replace the latest cache",
        ):
            signal_facts.command_bundle(args)


if __name__ == "__main__":
    unittest.main()
