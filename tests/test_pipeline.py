"""Basic tests for the Clinical Terminology Mapper.

These tests use only synthetic phrases and fake API responses. They do
not include real patient data and they do not require a live network
connection.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.pipeline import map_encounter
from src.schemas import EncounterInput, PhraseInput
from src.terminology.icd10 import (
    Icd10Client,
    TerminologyApiError as Icd10ApiError,
    is_valid_icd10cm_code,
    parse_search_response,
)
from src.terminology.rxnorm import (
    RxNormClient,
    TerminologyApiError as RxNormApiError,
    is_valid_rxcui,
    parse_properties_response,
    parse_rxcui_search_response,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENCOUNTERS_FILE = PROJECT_ROOT / "evaluation" / "synthetic_encounters.json"


class FakeIcd10Client:
    def __init__(self, candidates=None, error=None) -> None:
        self.candidates = candidates or []
        self.error = error
        self.phrases: list[str] = []

    def search(self, phrase: str):
        self.phrases.append(phrase)
        if self.error:
            raise self.error
        return list(self.candidates)


class FakeRxNormClient:
    def __init__(self, candidates=None, error=None) -> None:
        self.candidates = candidates or []
        self.error = error
        self.phrases: list[str] = []

    def search(self, phrase: str):
        self.phrases.append(phrase)
        if self.error:
            raise self.error
        return list(self.candidates)


class SchemaAndFileTests(unittest.TestCase):
    def test_synthetic_file_covers_five_required_scenarios(self) -> None:
        raw = json.loads(ENCOUNTERS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(raw), 5)
        scenarios = {item["scenario"] for item in raw}
        self.assertEqual(
            scenarios,
            {
                "straightforward diagnosis and medication",
                "negation",
                "historical condition",
                "uncertain diagnosis",
                "abbreviation",
            },
        )
        for item in raw:
            self.assertEqual(item["data_type"], "synthetic")
            self.assertIn("SYNTHETIC TEST NOTE", item["note"])
            self.assertTrue(item["encounter_id"].startswith("SYN-"))

    def test_mapping_json_uses_null_confidence(self) -> None:
        encounter = EncounterInput(
            encounter_id="SYN-TEST",
            note="SYNTHETIC TEST NOTE: adult with type 2 diabetes mellitus.",
            diagnoses=[PhraseInput(phrase="type 2 diabetes mellitus")],
        )
        from src.schemas import CodeCandidate

        results = map_encounter(
            encounter,
            icd10_client=FakeIcd10Client(
                candidates=[CodeCandidate(code="E11.9", description="Type 2 diabetes mellitus without complications")]
            ),
            rxnorm_client=FakeRxNormClient(),
        )
        payload = results[0].to_dict()
        self.assertIsNone(payload["confidence"])
        self.assertEqual(payload["suggested_code"], "E11.9")
        self.assertEqual(payload["review_status"], "needs_review")


class Icd10HelperTests(unittest.TestCase):
    def test_validates_icd10cm_code_shape(self) -> None:
        self.assertTrue(is_valid_icd10cm_code("E11.9"))
        self.assertTrue(is_valid_icd10cm_code("T58.11XA"))
        self.assertFalse(is_valid_icd10cm_code("not-a-code"))
        self.assertFalse(is_valid_icd10cm_code("E11.9-FAKE"))

    def test_parse_keeps_only_validated_api_rows(self) -> None:
        payload = [
            2,
            ["E11.9", "FAKE"],
            None,
            [
                ["E11.9", "Type 2 diabetes mellitus without complications"],
                ["NOT_A_CODE", "Should be dropped"],
            ],
        ]
        candidates = parse_search_response(payload)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].code, "E11.9")

    def test_parse_rejects_unexpected_shape(self) -> None:
        with self.assertRaises(Icd10ApiError):
            parse_search_response({"unexpected": True})

    def test_client_does_not_call_api_for_blank_phrase(self) -> None:
        def fail_if_called(url, params):
            raise AssertionError("Blank phrases must not call the API.")

        client = Icd10Client(get_json=fail_if_called)
        self.assertEqual(client.search("   "), [])


class RxNormHelperTests(unittest.TestCase):
    def test_validates_numeric_rxcui(self) -> None:
        self.assertTrue(is_valid_rxcui("6809"))
        self.assertFalse(is_valid_rxcui("metformin"))
        self.assertFalse(is_valid_rxcui("68-09"))

    def test_parse_search_ids_and_properties(self) -> None:
        ids = parse_rxcui_search_response({"idGroup": {"rxnormId": ["6809", "not-an-id"]}})
        self.assertEqual(ids, ["6809"])
        candidate = parse_properties_response(
            {"properties": {"rxcui": "6809", "name": "metformin"}}
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.code, "6809")
        self.assertEqual(candidate.description, "metformin")

    def test_missing_properties_are_not_treated_as_valid_codes(self) -> None:
        self.assertIsNone(parse_properties_response({"properties": None}))

    def test_client_validates_search_hits_with_properties(self) -> None:
        calls: list[str] = []

        def fake_get(url: str, params: dict[str, str]):
            calls.append(url)
            if url.endswith("/rxcui.json"):
                return {"idGroup": {"rxnormId": ["6809"]}}
            if url.endswith("/rxcui/6809/properties.json"):
                return {"properties": {"rxcui": "6809", "name": "metformin"}}
            raise AssertionError(f"Unexpected URL {url}")

        client = RxNormClient(get_json=fake_get)
        candidates = client.search("metformin")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].code, "6809")
        self.assertTrue(any(url.endswith("/rxcui.json") for url in calls))
        self.assertTrue(any("properties.json" in url for url in calls))


class PipelineTests(unittest.TestCase):
    def test_maps_diagnosis_and_medication_without_inventing_codes(self) -> None:
        from src.schemas import CodeCandidate

        encounter = EncounterInput(
            encounter_id="SYN-001",
            note="SYNTHETIC TEST NOTE: type 2 diabetes mellitus treated with metformin.",
            diagnoses=[PhraseInput(phrase="type 2 diabetes mellitus")],
            medications=[PhraseInput(phrase="metformin")],
        )
        results = map_encounter(
            encounter,
            icd10_client=FakeIcd10Client(
                candidates=[
                    CodeCandidate(code="E11.9", description="Type 2 diabetes mellitus without complications"),
                    CodeCandidate(code="E11.65", description="Type 2 diabetes mellitus with hyperglycemia"),
                ]
            ),
            rxnorm_client=FakeRxNormClient(
                candidates=[CodeCandidate(code="6809", description="metformin")]
            ),
        )
        self.assertEqual(len(results), 2)
        diagnosis, medication = results
        self.assertEqual(diagnosis.suggested_code, "E11.9")
        self.assertEqual(diagnosis.alternatives[0].code, "E11.65")
        self.assertEqual(diagnosis.code_system, "ICD-10-CM")
        self.assertEqual(medication.suggested_code, "6809")
        self.assertEqual(medication.code_system, "RxNorm")
        self.assertIsNone(diagnosis.confidence)
        self.assertIsNone(medication.confidence)

    def test_empty_results_and_api_errors_are_explicit(self) -> None:
        encounter = EncounterInput(
            encounter_id="SYN-EMPTY",
            note="SYNTHETIC TEST NOTE: blank lookup.",
            diagnoses=[PhraseInput(phrase="unknown condition xyz")],
            medications=[PhraseInput(phrase="mystery-drug")],
        )
        results = map_encounter(
            encounter,
            icd10_client=FakeIcd10Client(candidates=[]),
            rxnorm_client=FakeRxNormClient(error=RxNormApiError("RxNorm API request timed out.")),
        )
        self.assertEqual(results[0].review_status, "no_code_found")
        self.assertIsNone(results[0].suggested_code)
        self.assertEqual(results[1].review_status, "api_error")
        self.assertIsNone(results[1].suggested_code)
        self.assertIn("timed out", results[1].error_message)

    def test_blank_phrase_does_not_search(self) -> None:
        encounter = EncounterInput(
            encounter_id="SYN-BLANK",
            note="SYNTHETIC TEST NOTE: missing phrase.",
            diagnoses=[PhraseInput(phrase="")],
        )
        icd10 = FakeIcd10Client()
        map_encounter(encounter, icd10_client=icd10, rxnorm_client=FakeRxNormClient())
        self.assertEqual(icd10.phrases, [])

    def test_negated_phrase_is_still_flagged_for_review(self) -> None:
        from src.schemas import CodeCandidate

        encounter = EncounterInput(
            encounter_id="SYN-002",
            note="SYNTHETIC TEST NOTE: adult denies chest pain.",
            diagnoses=[PhraseInput(phrase="chest pain", clinical_context="negated")],
        )
        results = map_encounter(
            encounter,
            icd10_client=FakeIcd10Client(
                candidates=[CodeCandidate(code="R07.9", description="Chest pain, unspecified")]
            ),
            rxnorm_client=FakeRxNormClient(),
        )
        self.assertEqual(results[0].clinical_context, "negated")
        self.assertEqual(results[0].review_status, "needs_review")
        self.assertEqual(results[0].suggested_code, "R07.9")


if __name__ == "__main__":
    unittest.main()
