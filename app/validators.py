"""Deterministic guards, not a semantic proof of model-generated prose.

Numeric membership does not establish that a value was assigned to the right
field or that a relationship is true. The dashboard always includes engine facts.
"""

import math
import re
import unicodedata
from decimal import Decimal, DecimalException

from data.generate_samples import EXCEPTION_TYPES


VALIDATORS = (
    "faithfulness", "answer_relevance", "classification_in_set",
    "plan_coherence", "injection_scan", "pii_scan",
)
DEFAULT_THRESHOLDS = {name: 1.0 for name in VALIDATORS}
IDENTIFIER = re.compile(r"(?<!\w)SYN[-‐‑–—][LP][\w‐‑–—-]*", re.I)
DATE = re.compile(r"(?<!\w)\d{4}-\d{2}(?:-\d{2})?(?!\w)")
NUMBER = re.compile(r"(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])")


def _atoms(text):
    identifiers = set(IDENTIFIER.findall(text))
    stripped = IDENTIFIER.sub(" ", text)
    dates = set(DATE.findall(stripped))
    stripped = DATE.sub(" ", stripped)
    numbers = {Decimal(match.replace(",", "")) for match in NUMBER.findall(stripped)}
    return identifiers, dates, numbers


def faithfulness(rationale, evidence, engine_detail):
    if not isinstance(rationale, str) or not rationale.strip():
        return 0.0, ["No completed rationale available"]
    # Values only: row numbers, paths and arbitrary JSON keys are not grounding.
    source = engine_detail + " " + " ".join(
        str(value) for row in evidence for value in row.get("raw", {}).values()
    )
    try:
        expected = _atoms(source)
        actual = _atoms(rationale)
    except DecimalException:
        return 0.0, ["Unsupported numeric representation requires review"]
    findings = []
    for label, supplied, allowed in zip(("loan/posting ID", "period/date", "number"), actual, expected):
        for value in sorted(supplied - allowed):
            findings.append(f"Ungrounded {label}: {value}")
    # NFKC catches full-width identifier disguises without silently accepting them.
    normalized_ids = _atoms(unicodedata.normalize("NFKC", rationale))[0]
    if normalized_ids != actual[0]:
        findings.append("Nonstandard identifier characters require review")
    return (0.0 if findings else 1.0), findings


def answer_relevance(rationale, ex_type, loan_id):
    vocabulary = {
        "MISSING_PAYMENT": r"missing|missed|no payment|zero|net received 0",
        "DUPLICATE_DIRECT_DEBIT": r"duplicate|multiple.*debit|direct.debit postings",
        "RATE_MARGIN_BREACH": r"margin|rate.*breach",
    }
    findings = []
    if not re.search(r"(?<!\w)" + re.escape(loan_id) + r"(?![\w-])", rationale):
        findings.append("Rationale does not identify the exception loan")
    if ex_type not in vocabulary or not re.search(vocabulary[ex_type], rationale, re.I):
        findings.append("Rationale does not discuss the exception type")
    if re.search(r"\b(?:transfer|wire|send|pay|refund|debit|collect)\s+(?:now|immediately|[£€$]?\d)|\b(?:bank account|payment instructions)\b", rationale, re.I):
        findings.append("Actionable payment instruction requires human review")
    return (0.0 if findings else 1.0), findings


def classification_in_set(cls):
    valid = isinstance(cls, dict) and cls.get("type") in EXCEPTION_TYPES
    return (1.0, []) if valid else (0.0, ["Classification is outside the closed exception set"])


def plan_coherence(spans):
    engine = [i for i, span in enumerate(spans) if span.get("name") == "reconcile_engine" and span.get("status") == "success"]
    drafts = [i for i, span in enumerate(spans) if span.get("name") == "draft_rationale"]
    valid = bool(engine) and all(engine[0] < draft for draft in drafts)
    return (1.0, []) if valid else (0.0, ["A successful engine step must precede every draft"])


def _scan(rows, patterns):
    findings = []
    for index, row in enumerate(rows, start=1):
        values = row.values() if isinstance(row, dict) else [row]
        for value in values:
            normalized = unicodedata.normalize("NFKC", str(value))
            for label, pattern in patterns:
                if re.search(pattern, normalized, re.I):
                    # Do not copy flagged PII/instructions to the public response.
                    findings.append(f"Input record {index}: {label}")
    return (0.0 if findings else 1.0), findings


def injection_scan(rows):
    return _scan(rows, (
        ("instruction override", r"ignore\s+(?:(?:all|the|any)\s+)?(?:previous|prior|above|system)\s+instructions"),
        ("role delimiter", r"<\|(?:im_start|system)|\[INST\]|(?:system|assistant)\s*:\s*"),
        ("instruction disclosure", r"reveal.{0,30}(?:system prompt|api key)|you are now|override.{0,20}(?:policy|instructions)"),
    ))


def pii_scan(rows):
    return _scan(rows, (
        ("email pattern", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        ("IBAN pattern", r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b"),
        ("phone pattern", r"(?<!\w)(?:\+\d[\d ()-]{8,}\d|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})(?!\w)"),
    ))


def apply_policy(scores, thresholds=None, external_verdict=None):
    """Missing/invalid scores fail closed; an external BLOCK can only tighten."""
    thresholds = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    if external_verdict not in (None, "PASS") or not thresholds:
        return "BLOCK"
    for name, threshold in thresholds.items():
        score = scores.get(name)
        if any(isinstance(value, bool) or not isinstance(value, (float, int)) or
               not math.isfinite(value) or not 0 <= value <= 1 for value in (score, threshold)):
            return "BLOCK"
        if score < threshold:
            return "BLOCK"
    return "PASS"
