"""RxNorm lookup against the official NLM RxNorm REST API.

API docs:
    https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html

Why two API calls:
    1. Search by name to get RxCUI identifiers. We try an exact-then-
       normalized search first (`search=2`). If that is empty, we try
       approximate match (`search=9`) so abbreviations like HCTZ can
       still resolve.
    2. Fetch properties for each RxCUI. If NLM has no properties, the
       identifier is not an active RxNorm concept and we drop it.

This module never invents an RxCUI. If NLM does not return one, we
return no candidates and let the pipeline mark the row as no_code_found
or api_error.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import requests

from src.schemas import CodeCandidate

DEFAULT_RXNORM_URL = "https://rxnav.nlm.nih.gov/REST"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_CANDIDATES = 5
USER_AGENT = "ClinicalTerminologyMapper/0.1 (synthetic-educational-prototype)"
RXCUI_PATTERN = re.compile(r"^\d+$")

GetJson = Callable[[str, dict[str, str]], Any]


class TerminologyApiError(Exception):
    """Raised when the RxNorm API cannot be reached or returns bad data."""


def is_valid_rxcui(code: str) -> bool:
    """RxCUIs are numeric identifiers assigned by NLM, never by this app."""

    return bool(RXCUI_PATTERN.fullmatch(code.strip()))


def parse_rxcui_search_response(payload: Any) -> list[str]:
    """Extract RxCUI strings from /REST/rxcui.json."""

    if not isinstance(payload, dict):
        raise TerminologyApiError("RxNorm search returned an unexpected JSON shape.")

    id_group = payload.get("idGroup") or {}
    if not isinstance(id_group, dict):
        raise TerminologyApiError("RxNorm search idGroup was not a JSON object.")

    raw_ids = id_group.get("rxnormId") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        raise TerminologyApiError("RxNorm search rxnormId was not a list or string.")

    codes: list[str] = []
    for item in raw_ids:
        code = str(item).strip()
        if is_valid_rxcui(code) and code not in codes:
            codes.append(code)
    return codes


def parse_properties_response(payload: Any) -> CodeCandidate | None:
    """Keep a concept only when NLM returns an official name for the RxCUI."""

    if not isinstance(payload, dict):
        raise TerminologyApiError("RxNorm properties returned an unexpected JSON shape.")

    properties = payload.get("properties")
    if not properties or not isinstance(properties, dict):
        return None

    code = str(properties.get("rxcui", "")).strip()
    name = str(properties.get("name", "")).strip()
    if not is_valid_rxcui(code) or not name:
        return None
    return CodeCandidate(code=code, description=name)


def _default_get_json(url: str, params: dict[str, str], timeout_seconds: float) -> Any:
    try:
        response = requests.get(
            url,
            params=params or None,
            timeout=timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout as exc:
        raise TerminologyApiError("RxNorm API request timed out.") from exc
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise TerminologyApiError(f"RxNorm API returned HTTP {status}.") from exc
    except requests.RequestException as exc:
        raise TerminologyApiError("RxNorm API request failed.") from exc
    except ValueError as exc:
        raise TerminologyApiError("RxNorm API returned invalid JSON.") from exc


class RxNormClient:
    """Small wrapper around official RxNorm search + property lookup."""

    def __init__(
        self,
        base_url: str = DEFAULT_RXNORM_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        get_json: GetJson | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_candidates = max_candidates
        self._get_json = get_json

    def _get(self, url: str, params: dict[str, str] | None = None) -> Any:
        query = params or {}
        if self._get_json is None:
            return _default_get_json(url, query, self.timeout_seconds)
        return self._get_json(url, query)

    def search(self, phrase: str) -> list[CodeCandidate]:
        """Search RxNorm and return only concepts NLM can validate by RxCUI."""

        cleaned = phrase.strip()
        if not cleaned:
            return []

        rxcui_list = self._find_rxcuis(cleaned, search_mode="2")
        if not rxcui_list:
            rxcui_list = self._find_rxcuis(cleaned, search_mode="9")

        candidates: list[CodeCandidate] = []
        for rxcui in rxcui_list:
            if len(candidates) >= self.max_candidates:
                break
            properties_url = f"{self.base_url}/rxcui/{rxcui}/properties.json"
            candidate = parse_properties_response(self._get(properties_url))
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _find_rxcuis(self, phrase: str, search_mode: str) -> list[str]:
        search_url = f"{self.base_url}/rxcui.json"
        payload = self._get(search_url, {"name": phrase, "search": search_mode})
        return parse_rxcui_search_response(payload)
