# Clinical Terminology Mapper

A prototype that converts clinical text into validated ICD-10-CM diagnosis and RxNorm medication mappings using synthetic test data.

This first version is a small, beginner-friendly Python pipeline. It does **not** transcribe audio, open a website, send data to FHIR, deploy to AWS, or fine-tune a model. It also does **not** call an LLM yet.

## What this version does

1. Reads one synthetic clinical note plus a **manually supplied** list of diagnosis and medication phrases.
2. Searches official terminology APIs for those phrases.
3. Keeps only codes the APIs actually returned and that pass a format check.
4. Prints structured JSON for a human to review.

The app never invents a medical code. If the API fails or returns nothing, the JSON says so.

## Safety rules

- Use only synthetic or fully de-identified test data.
- Never put real patient names, dates of birth, medical record numbers, or notes in this project.
- Do not treat `suggested_code` as a final billed or documented code. Every successful row is `needs_review`.
- `confidence` is always `null`. A made-up score would look precise without being valid.

## Project layout

| File | What it is for |
| --- | --- |
| `README.md` | This guide: setup, run, and design notes. |
| `.gitignore` | Tells Git to ignore secrets, virtual environments, and OS junk. |
| `.env.example` | Sample settings you can copy to `.env`. No API key is required. |
| `requirements.txt` | The small list of Python packages to install. |
| `src/__init__.py` | Marks `src` as a Python package so imports like `from src.pipeline import ...` work. |
| `src/main.py` | Command-line entry point. Loads synthetic encounters and prints JSON. |
| `src/schemas.py` | Shared field names and types for inputs and outputs. |
| `src/pipeline.py` | Steps through each phrase, calls the right API, and builds the JSON rows. |
| `src/terminology/__init__.py` | Package file for the API clients. |
| `src/terminology/icd10.py` | ICD-10-CM search using the NLM Clinical Tables API. |
| `src/terminology/rxnorm.py` | Medication search using the official NLM RxNorm API. |
| `tests/__init__.py` | Marks `tests` as a package. |
| `tests/test_pipeline.py` | Basic tests with fake API responses and synthetic phrases only. |
| `evaluation/synthetic_encounters.json` | Five made-up encounters used for local runs. |

## Important coding decisions

**No LLM in version 1.** Phrase extraction is not automated. Each synthetic encounter already lists the phrases to search. That keeps the first version small and avoids an LLM guessing codes.

**Authoritative APIs only.** Diagnoses go to the [NLM Clinical Tables ICD-10-CM API](https://clinicaltables.nlm.nih.gov/apidoc/icd10cm/v3/doc.html). Medications go to the [NLM RxNorm REST API](https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html). The first API hit becomes `suggested_code`. Extra validated hits become `alternatives`.

**Validate before keeping a code.** ICD-10-CM codes must match the usual code pattern (for example `E11.9`). RxNorm IDs must be numeric RxCUIs, and each ID is checked with RxNorm's properties endpoint so inactive or empty concepts are dropped.

**Review flags stay honest.** Negated, historical, and uncertain phrases are still searched so you can see what the API returned, but they stay `needs_review`. Version 1 does not decide that a denied symptom should be coded.

**Modular clients.** `pipeline.py` can accept fake API clients. Tests use those fakes so they do not need the internet or real patient data. A later company backend can call `map_encounter()` the same way.

## Windows setup

Use PowerShell. Run these commands from the project folder
(`scribe-terminology-mapper`).

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

If Windows blocks the virtual environment script, run this once in that PowerShell window, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

You should see `(.venv)` at the start of the prompt after activation.

## Run the mapper

Still inside the activated virtual environment, from the project folder:

```powershell
python -m src.main
```

That maps all five synthetic encounters and prints JSON.

Run one encounter:

```powershell
python -m src.main --encounter-id SYN-001
```

Optional: point at another synthetic JSON file with the same shape:

```powershell
python -m src.main --encounters-file evaluation\synthetic_encounters.json
```

## Run the tests

```powershell
python -m unittest
```

The tests mock terminology APIs. They do not send real patient data anywhere.

## Output fields

Each JSON row contains:

| Field | Meaning |
| --- | --- |
| `encounter_id` | ID from the synthetic file, such as `SYN-001`. |
| `source_text` | The full synthetic note. |
| `source_phrase` | The manually supplied phrase that was searched. |
| `clinical_context` | `current`, `negated`, `historical`, or `uncertain`. |
| `entity_type` | `diagnosis` or `medication`. |
| `code_system` | `ICD-10-CM` or `RxNorm`. |
| `suggested_code` | First validated API candidate, or `null`. |
| `description` | Official description for that candidate, or `null`. |
| `alternatives` | Other validated API candidates. |
| `review_status` | `needs_review`, `no_code_found`, or `api_error`. |
| `confidence` | Always `null` in this version. |
| `error_message` | Details when a lookup fails or is empty, otherwise `null`. |

## Synthetic evaluation cases

All notes in `evaluation/synthetic_encounters.json` are labeled `SYNTHETIC TEST NOTE` and contain no real patient identifiers.

| ID | What it exercises |
| --- | --- |
| SYN-001 | Straightforward diagnosis (`type 2 diabetes mellitus`) and medication (`metformin`). |
| SYN-002 | Negation (`denies chest pain`). |
| SYN-003 | Historical condition (`history of myocardial infarction`). |
| SYN-004 | Uncertain diagnosis (`possible pneumonia`). |
| SYN-005 | Abbreviation (`UTI` and `HCTZ`). |

SYN-005 is a safety example: RxNorm can expand `HCTZ` to hydrochlorothiazide, but the ICD-10-CM search for `UTI` may return unrelated codes because the API is matching letters, not clinical meaning. That is why a person must review every row.

## Later versions (not built yet)

Possible next steps, without changing this version's scope:

- Use an LLM only to extract phrases, never to invent codes.
- Add a human review UI.
- Send approved codes into a company backend or FHIR resources.
- Add more code systems after the current two are solid.
