"""Shared data shapes for the Clinical Terminology Mapper.

Why this file exists:
    Other modules should agree on the same field names. Putting those
    shapes in one place makes the pipeline easier to plug into a company
    backend later.

Why dataclasses:
    A dataclass is a beginner-friendly way to say "this object has these
    named fields and types" without writing a lot of boilerplate.

Why confidence is always None:
    This first version does not score how "sure" a mapping is. Returning
    null is honest. A made-up number would look scientific but would not
    be valid.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EntityType = Literal["diagnosis", "medication"]
CodeSystem = Literal["ICD-10-CM", "RxNorm"]
ClinicalContext = Literal["current", "negated", "historical", "uncertain"]
ReviewStatus = Literal["needs_review", "no_code_found", "api_error"]


@dataclass
class PhraseInput:
    """One manually supplied clinical phrase to look up.

    phrase: Text we will send to an official terminology API.
    clinical_context: Extra hint from the synthetic test file, not inferred
        by an LLM. "negated" means the note denied the finding.
    """

    phrase: str
    clinical_context: ClinicalContext = "current"


@dataclass
class EncounterInput:
    """One synthetic encounter: a note plus the phrases a human already listed."""

    encounter_id: str
    note: str
    diagnoses: list[PhraseInput] = field(default_factory=list)
    medications: list[PhraseInput] = field(default_factory=list)


@dataclass
class CodeCandidate:
    """One code returned by an authoritative terminology API."""

    code: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "description": self.description}


@dataclass
class MappingResult:
    """One mapped entity ready to serialize as JSON.

    suggested_code is the first validated API candidate, never a code that
    we invented. A human still needs to review it, especially for negated,
    historical, or uncertain phrases.
    """

    encounter_id: str
    source_text: str
    entity_type: EntityType
    code_system: CodeSystem
    suggested_code: str | None
    description: str | None
    alternatives: list[CodeCandidate]
    review_status: ReviewStatus
    source_phrase: str
    clinical_context: ClinicalContext
    confidence: None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = None
        return payload


def encounter_from_dict(raw: dict[str, Any]) -> EncounterInput:
    """Convert one JSON object from the evaluation file into EncounterInput."""

    diagnoses = [
        PhraseInput(
            phrase=str(item.get("phrase", "")).strip(),
            clinical_context=item.get("clinical_context", "current"),
        )
        for item in raw.get("diagnoses", [])
    ]
    medications = [
        PhraseInput(
            phrase=str(item.get("phrase", "")).strip(),
            clinical_context=item.get("clinical_context", "current"),
        )
        for item in raw.get("medications", [])
    ]
    return EncounterInput(
        encounter_id=str(raw.get("encounter_id", "")).strip(),
        note=str(raw.get("note", "")).strip(),
        diagnoses=diagnoses,
        medications=medications,
    )
