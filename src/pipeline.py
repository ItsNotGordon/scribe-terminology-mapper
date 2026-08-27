"""Orchestrate phrase lookup without inventing medical codes.

This first version does not use an LLM. A caller (or the synthetic JSON
file) must already supply diagnosis and medication phrases. The pipeline
then:

1. Sends each phrase to the matching official API.
2. Takes the first validated candidate as suggested_code.
3. Puts remaining validated candidates in alternatives.
4. Leaves confidence as null.
5. Marks every successful row needs_review so a person still decides.

Negated, historical, and uncertain phrases are still searched so a
reviewer can see what the APIs returned, but they are never treated as
final coded facts.
"""

from __future__ import annotations

import os
from typing import Any

from src.schemas import (
    CodeCandidate,
    EncounterInput,
    MappingResult,
    PhraseInput,
    ReviewStatus,
)
from src.terminology.icd10 import Icd10Client, TerminologyApiError as Icd10ApiError
from src.terminology.rxnorm import RxNormClient, TerminologyApiError as RxNormApiError


def load_settings_from_env() -> dict[str, Any]:
    """Read optional API settings. Missing values fall back to official NLM URLs."""

    timeout_raw = os.getenv("TERMINOLOGY_API_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 10.0

    return {
        "timeout_seconds": timeout_seconds,
        "icd10_base_url": os.getenv(
            "ICD10_API_BASE_URL",
            "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search",
        ).strip(),
        "rxnorm_base_url": os.getenv(
            "RXNORM_API_BASE_URL",
            "https://rxnav.nlm.nih.gov/REST",
        ).strip(),
    }


def build_clients(
    icd10_client: Icd10Client | None = None,
    rxnorm_client: RxNormClient | None = None,
) -> tuple[Icd10Client, RxNormClient]:
    """Use injected clients in tests, or real NLM clients in normal runs."""

    settings = load_settings_from_env()
    if icd10_client is None:
        icd10_client = Icd10Client(
            base_url=settings["icd10_base_url"],
            timeout_seconds=settings["timeout_seconds"],
        )
    if rxnorm_client is None:
        rxnorm_client = RxNormClient(
            base_url=settings["rxnorm_base_url"],
            timeout_seconds=settings["timeout_seconds"],
        )
    return icd10_client, rxnorm_client


def map_encounter(
    encounter: EncounterInput,
    icd10_client: Icd10Client | None = None,
    rxnorm_client: RxNormClient | None = None,
) -> list[MappingResult]:
    """Map one synthetic encounter's manually supplied phrases."""

    icd10_client, rxnorm_client = build_clients(icd10_client, rxnorm_client)
    results: list[MappingResult] = []

    for phrase in encounter.diagnoses:
        results.append(
            _map_phrase(
                encounter=encounter,
                phrase=phrase,
                entity_type="diagnosis",
                code_system="ICD-10-CM",
                search=icd10_client.search,
                api_error_type=Icd10ApiError,
            )
        )

    for phrase in encounter.medications:
        results.append(
            _map_phrase(
                encounter=encounter,
                phrase=phrase,
                entity_type="medication",
                code_system="RxNorm",
                search=rxnorm_client.search,
                api_error_type=RxNormApiError,
            )
        )

    return results


def _map_phrase(
    encounter: EncounterInput,
    phrase: PhraseInput,
    entity_type: str,
    code_system: str,
    search: Any,
    api_error_type: type[Exception],
) -> MappingResult:
    if not phrase.phrase:
        return _result(
            encounter,
            phrase,
            entity_type,
            code_system,
            suggested=None,
            alternatives=[],
            review_status="no_code_found",
            error_message="No search phrase was supplied.",
        )

    try:
        candidates = search(phrase.phrase)
    except api_error_type as exc:
        return _result(
            encounter,
            phrase,
            entity_type,
            code_system,
            suggested=None,
            alternatives=[],
            review_status="api_error",
            error_message=str(exc),
        )

    if not candidates:
        return _result(
            encounter,
            phrase,
            entity_type,
            code_system,
            suggested=None,
            alternatives=[],
            review_status="no_code_found",
            error_message="The terminology API returned no validated codes.",
        )

    suggested, *alternatives = candidates
    return _result(
        encounter,
        phrase,
        entity_type,
        code_system,
        suggested=suggested,
        alternatives=alternatives,
        review_status="needs_review",
        error_message=None,
    )


def _result(
    encounter: EncounterInput,
    phrase: PhraseInput,
    entity_type: str,
    code_system: str,
    suggested: CodeCandidate | None,
    alternatives: list[CodeCandidate],
    review_status: ReviewStatus,
    error_message: str | None,
) -> MappingResult:
    return MappingResult(
        encounter_id=encounter.encounter_id,
        source_text=encounter.note,
        entity_type=entity_type,  # type: ignore[arg-type]
        code_system=code_system,  # type: ignore[arg-type]
        suggested_code=suggested.code if suggested else None,
        description=suggested.description if suggested else None,
        alternatives=alternatives,
        review_status=review_status,
        source_phrase=phrase.phrase,
        clinical_context=phrase.clinical_context,
        confidence=None,
        error_message=error_message,
    )
