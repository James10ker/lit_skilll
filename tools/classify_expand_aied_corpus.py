#!/usr/bin/env python3
"""Classify an AIEd corpus and expand it along reference-review directions.

The taxonomy is aligned with Figure 10 and the future-direction discussion in
Chen et al. (2022), while retaining explicit buckets for post-2019 AIEd topics.
The original input is never modified. Expansion records are retrieved from the
OpenAlex Works API and deduplicated by OpenAlex ID, DOI, and normalized title.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REFERENCE_TITLE = (
    "Two Decades of Artificial Intelligence in Education: Contributors, "
    "Collaborations, Research Topics, Challenges, and Future Directions"
)


@dataclass(frozen=True)
class TopicRule:
    code: str
    label: str
    reference_group: str
    patterns: tuple[str, ...]


TOPIC_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        "T01",
        "Intelligent tutoring for writing and reading",
        "reference_topic",
        (
            r"writing\s+(?:pal|tutor)",
            r"reading\s+(?:tutor|comprehension)",
            r"intelligent tutor(?:ing)?[^.]{0,50}(?:writing|reading|literacy)",
            r"(?:writing|reading|literacy)[^.]{0,50}intelligent tutor",
        ),
    ),
    TopicRule(
        "T02",
        "ITS authoring and scaffolding",
        "reference_topic",
        (
            r"authoring (?:tool|system|environment)",
            r"scaffold(?:ing|ed|s)?",
            r"example[- ]tracing tutor",
            r"help[- ]seeking",
            r"(?:hint|feedback)[^.]{0,40}(?:tutor|tutoring system)",
        ),
    ),
    TopicRule(
        "T03",
        "Computer science and AI education",
        "reference_topic",
        (
            r"computer science education",
            r"programming education",
            r"teach(?:ing)? (?:programming|machine learning|artificial intelligence|ai)",
            r"learn(?:ing)? (?:programming|machine learning|artificial intelligence|ai)",
            r"ai literacy",
            r"machine learning education",
        ),
    ),
    TopicRule(
        "T04",
        "Game-based learning",
        "reference_topic",
        (r"game[- ]based learning", r"educational game", r"serious game", r"gamif(?:ication|ied|y)"),
    ),
    TopicRule(
        "T05",
        "ML-supported collaborative learning and discourse",
        "reference_topic",
        (
            r"computer[- ]supported collaborative learning",
            r"\bcscl\b",
            r"collaborative learning",
            r"collaborative discourse",
            r"discourse analysis",
        ),
    ),
    TopicRule(
        "T06",
        "NLP and dialogue systems for education",
        "reference_topic",
        (
            r"natural language processing",
            r"dialogue system",
            r"dialog system",
            r"conversational (?:agent|tutor|system)",
            r"educational chatbot",
            r"chatbot[^.]{0,40}(?:education|learning|teaching|student)",
        ),
    ),
    TopicRule(
        "T07",
        "Educational data mining and learning analytics",
        "reference_topic",
        (
            r"educational data mining",
            r"learning analytics",
            r"student (?:performance|success|dropout) prediction",
            r"predict(?:ing|ion of)? (?:student|academic|learning) performance",
            r"academic performance prediction",
            r"early warning system",
        ),
    ),
    TopicRule(
        "T08",
        "Problem-solving and example-based learning",
        "reference_topic",
        (r"problem[- ]solving", r"example[- ]based learning", r"worked example", r"solution trace"),
    ),
    TopicRule(
        "T09",
        "Ontology and knowledge management",
        "reference_topic",
        (
            r"ontolog(?:y|ies|ical)",
            r"knowledge management",
            r"semantic web",
            r"knowledge base[^.]{0,50}(?:education|learning|tutor|student)",
        ),
    ),
    TopicRule(
        "T10",
        "Adaptive testing and diagnosis systems",
        "reference_topic",
        (
            r"computerized adaptive test",
            r"computerised adaptive test",
            r"adaptive assessment",
            r"diagnos(?:is|tic)[^.]{0,40}(?:learner|student|knowledge|learning)",
            r"knowledge tracing",
            r"student model(?:ing|ling)?",
        ),
    ),
    TopicRule(
        "T11",
        "Intelligent systems for medical and professional training",
        "reference_topic",
        (
            r"virtual surgery",
            r"surgery training",
            r"medical education",
            r"clinical education",
            r"nursing education",
            r"radiology education",
            r"professional training",
        ),
    ),
    TopicRule(
        "T12",
        "Neural networks for prediction and teaching evaluation",
        "reference_topic",
        (
            r"artificial neural network",
            r"neural network",
            r"deep neural",
            r"convolutional neural",
            r"recurrent neural",
            r"\bcnn\b",
            r"\blstm\b",
        ),
    ),
    TopicRule(
        "T13",
        "Graphical representation and knowledge connection",
        "reference_topic",
        (
            r"graphical representation",
            r"knowledge connection",
            r"concept map",
            r"knowledge graph",
            r"learning visualization",
            r"learning visualisation",
        ),
    ),
    TopicRule(
        "T14",
        "Educational robots and robot-assisted learning",
        "reference_topic",
        (r"educational robot", r"robot[- ]assisted learning", r"social robot", r"robot tutor", r"robotics education"),
    ),
    TopicRule(
        "T15",
        "Affective computing and learner emotion",
        "reference_topic",
        (
            r"affective computing",
            r"affective learning",
            r"emotion (?:detection|recognition|regulation)",
            r"learner emotion",
            r"student emotion",
            r"affect detection",
            r"affective feedback",
        ),
    ),
    TopicRule(
        "T16",
        "Intelligent tutoring for K-12 and special education",
        "reference_topic",
        (
            r"\bk[-– ]?12\b",
            r"primary school",
            r"elementary school",
            r"secondary school",
            r"special education",
            r"autis(?:m|tic)",
            r"learning disabilit",
            r"special needs",
        ),
    ),
    TopicRule(
        "T17",
        "Recommender systems and personalized learning",
        "reference_future_extension",
        (
            r"educational recommender",
            r"recommender system",
            r"recommendation system",
            r"personalized learning",
            r"personalised learning",
            r"personalized learning path",
            r"personalised learning path",
        ),
    ),
    TopicRule(
        "E01",
        "Generative AI and large language models in education",
        "post_2019_extension",
        (
            r"generative (?:artificial intelligence|ai)",
            r"large language model",
            r"\bllms?\b",
            r"\bchatgpt\b",
            r"\bgpt[- ]?[234o]?\b",
            r"foundation model",
        ),
    ),
    TopicRule(
        "E02",
        "Ethics, governance, privacy, and fairness in AIEd",
        "post_2019_extension",
        (
            r"ethic(?:al|s)",
            r"privacy",
            r"data protection",
            r"algorithmic bias",
            r"fairness",
            r"responsible ai",
            r"governance",
            r"(?:ai|artificial intelligence) policy",
            r"policy[^.]{0,50}(?:ai|artificial intelligence)",
        ),
    ),
)


TOPIC_BY_CODE = {rule.code: rule for rule in TOPIC_RULES}

OTHER_AIED = {
    "code": "O01",
    "label": "Other or field-level AIEd research",
    "reference_group": "other_aied",
}
OUT_OF_SCOPE = {
    "code": "X00",
    "label": "Out of scope or insufficient AIEd evidence",
    "reference_group": "excluded",
}


FUTURE_DIRECTIONS: dict[str, dict[str, Any]] = {
    "F01": {
        "label": "ITS for special education",
        "target": 5,
        "queries": (
            '"intelligent tutoring system" "special education"',
            '"intelligent tutoring" autism education',
        ),
        "patterns": (r"(?:intelligent tutor|tutoring system)", r"(?:special education|autis|disabilit|special needs)"),
        "title_patterns": (r"(?:special education|autis|disabilit|special needs)",),
        "allowed_topic_codes": ("T01", "T02", "T12", "T14", "T16"),
    },
    "F02": {
        "label": "NLP for language education",
        "target": 5,
        "queries": (
            '"natural language processing" "language education"',
            '"intelligent tutoring" writing reading language',
        ),
        "patterns": (
            r"(?:natural language processing|dialogue|chatbot|writing tutor|reading tutor)",
            r"(?:language (?:learning|education|teaching|learner)|writing|reading|literacy)",
        ),
        "title_patterns": (
            r"(?:natural language processing|dialogue|chatbot|writing tutor|reading tutor)",
            r"(?:language (?:learning|education|teaching|learner)|writing|reading|literacy)",
        ),
    },
    "F03": {
        "label": "Educational robots for AI education",
        "target": 5,
        "queries": (
            '"educational robot" learning',
            '"robot-assisted learning" education',
        ),
        "patterns": (r"robot", r"(?:education|educational|teaching|student|school|classroom|language learning|learning outcome)"),
        "title_patterns": (r"robot", r"(?:education|educational|teaching|student|school|classroom|language learning|learning outcome)"),
    },
    "F04": {
        "label": "EDM for performance prediction",
        "target": 5,
        "queries": (
            '"educational data mining" "student performance prediction"',
            '"learning analytics" "academic performance prediction"',
        ),
        "patterns": (r"(?:educational data mining|learning analytics)", r"(?:predict|performance|dropout|early warning|retention)"),
        "title_patterns": (r"(?:educational data mining|learning analytics)", r"(?:predict|performance|dropout|early warning|retention)"),
    },
    "F05": {
        "label": "Discourse analysis in CSCL",
        "target": 5,
        "queries": (
            '"discourse analysis" "computer-supported collaborative learning"',
            'machine learning CSCL collaborative discourse',
        ),
        "patterns": (r"(?:discourse|cscl|computer.supported collaborative|collaborative learning)", r"(?:analysis|machine learning|artificial intelligence|automated)"),
        "title_patterns": (r"(?:discourse|cscl|computer.supported collaborative|collaborative learning)", r"(?:analysis|machine learning|artificial intelligence|automated)"),
    },
    "F06": {
        "label": "Neural networks for teaching evaluation",
        "target": 5,
        "queries": (
            '"neural network" "teaching evaluation"',
            '"neural network" "teaching quality evaluation" education',
        ),
        "patterns": (
            r"(?:neural networks?|\bcnn\b|\blstm\b|deep learning(?:[- ]based| (?:model|algorithm|technique|method|architecture))|using deep learning)",
            r"(?:teaching(?: quality)? evaluation|evaluation of [^.]{0,30} teaching|classroom teaching behavior)",
        ),
        "title_patterns": (
            r"(?:neural networks?|\bcnn\b|\blstm\b|deep learning(?:[- ]based| (?:model|algorithm|technique|method|architecture))|using deep learning)",
            r"(?:teaching(?: quality)? evaluation|evaluation of [^.]{0,30} teaching|classroom teaching behavior)",
        ),
        "allowed_topic_codes": ("T07", "T12", "T15"),
    },
    "F07": {
        "label": "Affective computing for learner emotion detection",
        "target": 5,
        "queries": (
            '"affective computing" learner emotion education',
            '"emotion detection" "intelligent tutoring system"',
        ),
        "patterns": (
            r"\b(?:affect(?:ive)?|emotion(?:al)?)\w*\b",
            r"\b(?:learner|learners|student|students|education|educational|tutor|tutors|tutoring)\b|learning (?:environment|process)",
        ),
        "title_patterns": (
            r"\b(?:affect(?:ive)?|emotion(?:al)?)\w*\b",
            r"\b(?:learner|learners|student|students|education|educational|tutor|tutors|tutoring)\b|learning (?:environment|process)",
        ),
    },
    "F08": {
        "label": "Recommender systems for personalized learning",
        "target": 5,
        "queries": (
            '"educational recommender system" personalized learning',
            '"recommender system" adaptive learning education',
        ),
        "patterns": (r"(?:recommender|recommendation system)", r"(?:education|learning|student|course|personaliz|personalis)"),
        "title_patterns": (
            r"(?:recommender|recommendation system)",
            r"(?:e-learning|education|educational|student|course|learning (?:object|resource|path|system))",
        ),
    },
    "M01": {
        "label": "AIEd bibliometrics, contributors, collaborations, and topic trends",
        "target": 10,
        "queries": (
            f'"{REFERENCE_TITLE}"',
            '"artificial intelligence in education" bibliometric review',
            '"artificial intelligence in education" topic trends collaboration institutions',
        ),
        "patterns": (r"artificial intelligence[^.]{0,25}education|aied", r"(?:bibliometric|review|trend|topic|collaboration|institution|country|contributor)"),
        "title_patterns": (r"artificial intelligence[^.]{0,25}education|aied", r"(?:bibliometric|review|trend|topic|collaboration|institution|country|contributor)"),
    },
}


EDUCATION_PATTERN = re.compile(
    r"\b(?:education|educational|learner|student|teacher|teaching|tutor|school|"
    r"classroom|pedagog|academic|assessment|curriculum|instruction)\w*\b",
    re.I,
)
AI_PATTERN = re.compile(
    r"\b(?:artificial intelligence|machine learning|deep learning|neural|intelligent|"
    r"data mining|learning analytics|natural language processing|nlp|chatbot|robot|"
    r"algorithm|predict|recommender|adaptive|knowledge tracing|affective computing)\w*\b",
    re.I,
)
REVIEW_PATTERN = re.compile(
    r"\b(?:systematic review|literature review|scoping review|meta-analysis|meta analysis|"
    r"bibliometric|survey|review of|research trends|state of the field|narrative overview)\b",
    re.I,
)


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_title(value: Any) -> str:
    text = normalize_space(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_doi(value: Any) -> str:
    text = normalize_space(value).lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text.strip()


def split_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_space(item) for item in value if normalize_space(item)]
    if not value:
        return []
    return [part.strip() for part in re.split(r"[;|\n]", str(value)) if part.strip()]


def _topic_scores(record: dict[str, Any]) -> tuple[dict[str, float], dict[str, list[str]]]:
    title = normalize_space(record.get("title"))
    abstract = normalize_space(record.get("abstract"))
    concepts = " ; ".join(split_values(record.get("concepts")))
    keywords = " ; ".join(split_values(record.get("keywords")))
    queries = " ; ".join(split_values(record.get("matched_queries")))
    sections = (("title", title, 5.0), ("abstract", abstract, 1.0), ("concepts", concepts, 1.5), ("keywords", keywords, 2.0), ("query", queries, 0.5))
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    for rule in TOPIC_RULES:
        for pattern in rule.patterns:
            compiled = re.compile(pattern, re.I)
            for section_name, text, weight in sections:
                match = compiled.search(text)
                if not match:
                    continue
                scores[rule.code] += weight
                marker = f"{section_name}:{normalize_space(match.group(0))[:100]}"
                if marker not in evidence[rule.code]:
                    evidence[rule.code].append(marker)
    return dict(scores), dict(evidence)


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    title = normalize_space(record.get("title"))
    abstract = normalize_space(record.get("abstract"))
    concepts = " ".join(split_values(record.get("concepts")))
    searchable = f"{title} {abstract} {concepts}"
    education_signal = bool(EDUCATION_PATTERN.search(searchable))
    ai_signal = bool(AI_PATTERN.search(searchable))
    scores, evidence = _topic_scores(record)
    ranked = sorted(scores, key=lambda code: (-scores[code], code))

    # Strong, reference-specific rules may establish AIEd scope even when the
    # generic AI expression is absent (for example, an AutoTutor paper).
    strong_topic_signal = any(scores[code] >= 5.0 for code in ranked)
    in_scope = education_signal and (ai_signal or strong_topic_signal)
    if not in_scope:
        primary = OUT_OF_SCOPE
        secondary: list[str] = []
        confidence = "high" if not education_signal else "medium"
    elif ranked and scores[ranked[0]] >= 3.0:
        primary_rule = TOPIC_BY_CODE[ranked[0]]
        primary = {
            "code": primary_rule.code,
            "label": primary_rule.label,
            "reference_group": primary_rule.reference_group,
        }
        top_score = scores[ranked[0]]
        second_score = scores[ranked[1]] if len(ranked) > 1 else 0.0
        secondary = [code for code in ranked[1:] if scores[code] >= 2.5][:4]
        if top_score >= 8.0 and top_score - second_score >= 2.5:
            confidence = "high"
        elif top_score >= 4.0:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        primary = OTHER_AIED
        secondary = [code for code in ranked if scores[code] >= 1.0][:4]
        confidence = "low"

    work_type = normalize_space(record.get("work_type") or record.get("type")) or "article"
    if REVIEW_PATTERN.search(f"{title} {abstract}"):
        work_type = "review"

    future_codes = infer_future_directions(record)
    return {
        "in_scope": in_scope,
        "primary_topic_code": primary["code"],
        "primary_topic_label": primary["label"],
        "reference_group": primary["reference_group"],
        "secondary_topic_codes": secondary,
        "secondary_topic_labels": [TOPIC_BY_CODE[code].label for code in secondary],
        "topic_scores": {code: round(scores[code], 2) for code in ranked},
        "matched_evidence": {code: evidence.get(code, []) for code in ranked},
        "confidence": confidence,
        "work_type_normalized": work_type,
        "future_direction_codes": future_codes,
        "future_direction_labels": [FUTURE_DIRECTIONS[code]["label"] for code in future_codes],
        "scope_signals": {"education": education_signal, "ai": ai_signal},
    }


def infer_future_directions(record: dict[str, Any]) -> list[str]:
    text = f"{normalize_space(record.get('title'))} {normalize_space(record.get('abstract'))}"
    codes: list[str] = []
    for code, spec in FUTURE_DIRECTIONS.items():
        if all(re.search(pattern, text, re.I) for pattern in spec["patterns"]):
            codes.append(code)
    return codes


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("input must be a JSON list or an object with a records list")
    return [record for record in records if isinstance(record, dict)]


def _coverage(record: dict[str, Any]) -> str:
    if normalize_space(record.get("downloaded_pdf") or record.get("pdf_filename")):
        return "full_text_local"
    if normalize_space(record.get("abstract")):
        return "abstract_only"
    return "metadata_only"


def classify_original(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        item = dict(record)
        item["corpus_id"] = f"original-{index:03d}"
        item["record_origin"] = "original_150"
        item["coverage"] = _coverage(record)
        item["classification"] = classify_record(record)
        output.append(item)
    return output


def reconstruct_abstract(inverted: Any) -> str:
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions = [(position, word) for word, values in inverted.items() for position in values]
    if not positions:
        return ""
    size = max(position for position, _ in positions) + 1
    words = [""] * size
    for position, word in positions:
        if 0 <= position < size:
            words[position] = word
    return normalize_space(" ".join(words))


def _location_source(record: dict[str, Any]) -> dict[str, Any]:
    location = record.get("primary_location") or {}
    source = location.get("source") or {}
    return source if isinstance(source, dict) else {}


def openalex_to_record(raw: dict[str, Any], direction_code: str, query: str) -> dict[str, Any]:
    authors: list[str] = []
    institutions: list[str] = []
    countries: list[str] = []
    authorships_out: list[dict[str, Any]] = []
    for authorship in raw.get("authorships") or []:
        author = authorship.get("author") or {}
        author_name = normalize_space(author.get("display_name"))
        if author_name and author_name not in authors:
            authors.append(author_name)
        author_institutions: list[str] = []
        author_countries: list[str] = []
        for institution in authorship.get("institutions") or []:
            name = normalize_space(institution.get("display_name"))
            country = normalize_space(institution.get("country_code"))
            if name and name not in institutions:
                institutions.append(name)
            if name and name not in author_institutions:
                author_institutions.append(name)
            if country and country not in countries:
                countries.append(country)
            if country and country not in author_countries:
                author_countries.append(country)
        if author_name:
            authorships_out.append(
                {"author": author_name, "institutions": author_institutions, "countries": author_countries}
            )

    primary_location = raw.get("primary_location") or {}
    best_oa = raw.get("best_oa_location") or {}
    source = _location_source(raw)
    source_name = normalize_space(source.get("display_name"))
    source_type = normalize_space(source.get("type"))
    raw_source_name = normalize_space(primary_location.get("raw_source_name"))
    if source_type == "repository" and raw_source_name:
        publication_name = re.split(
            r",\s*(?:vol(?:ume)?\.?|iss(?:ue)?\.?|no\.?|pp?\.?)\s*\b",
            raw_source_name,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if publication_name:
            source_name = publication_name
            source_type = "journal"
    topics = [normalize_space(topic.get("display_name")) for topic in raw.get("topics") or [] if normalize_space(topic.get("display_name"))]
    keywords = [normalize_space(keyword.get("display_name")) for keyword in raw.get("keywords") or [] if normalize_space(keyword.get("display_name"))]
    doi = normalize_doi(raw.get("doi"))
    record = {
        "record_origin": "openalex_expansion",
        "expansion_direction_code": direction_code,
        "expansion_direction_label": FUTURE_DIRECTIONS[direction_code]["label"],
        "matched_query": query,
        "title": normalize_space(raw.get("title")),
        "publication_year": raw.get("publication_year"),
        "work_type": normalize_space(raw.get("type")) or "article",
        "source_name": source_name,
        "source_type": source_type,
        "source_is_core": bool(source.get("is_core")),
        "openalex_id": normalize_space(raw.get("id")),
        "doi": doi,
        "landing_page_url": normalize_space(primary_location.get("landing_page_url") or raw.get("doi") or raw.get("id")),
        "oa_url": normalize_space((raw.get("open_access") or {}).get("oa_url") or best_oa.get("landing_page_url")),
        "pdf_url": normalize_space(best_oa.get("pdf_url") or primary_location.get("pdf_url")),
        "is_oa": bool((raw.get("open_access") or {}).get("is_oa")),
        "oa_status": normalize_space((raw.get("open_access") or {}).get("oa_status")),
        "cited_by_count": int(raw.get("cited_by_count") or 0),
        "openalex_relevance_score": float(raw.get("relevance_score") or 0.0),
        "authors": authors,
        "institutions": institutions,
        "countries": countries,
        "authorships": authorships_out,
        "topics": topics,
        "concepts": topics,
        "keywords": keywords,
        "abstract": reconstruct_abstract(raw.get("abstract_inverted_index")),
        "is_retracted": bool(raw.get("is_retracted")),
    }
    record["coverage"] = "abstract_only" if record["abstract"] else "metadata_only"
    record["classification"] = classify_record(record)
    return record


def fetch_openalex(query: str, per_page: int = 100, retries: int = 3) -> dict[str, Any]:
    params = {
        "search": query,
        "filter": "from_publication_date:2000-01-01,to_publication_date:2025-12-31,language:en,type:article",
        "per-page": str(per_page),
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "literature-review-skill/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"OpenAlex request failed for query {query!r}: {last_error}")


def _direction_match_score(record: dict[str, Any], direction_code: str) -> float:
    text = f"{normalize_space(record.get('title'))} {normalize_space(record.get('abstract'))}"
    title = normalize_space(record.get("title"))
    spec = FUTURE_DIRECTIONS[direction_code]
    patterns = spec["patterns"]
    if not all(re.search(pattern, text, re.I) for pattern in patterns):
        return -1.0
    if not all(re.search(pattern, title, re.I) for pattern in spec.get("title_patterns", ())):
        return -1.0
    allowed_topic_codes = set(spec.get("allowed_topic_codes", ()))
    primary_topic_code = (record.get("classification") or {}).get("primary_topic_code")
    if allowed_topic_codes and primary_topic_code not in allowed_topic_codes:
        return -1.0
    score = 20.0
    score += sum(8.0 for pattern in patterns if re.search(pattern, title, re.I))
    score += min(12.0, math.log10(max(0, int(record.get("cited_by_count") or 0)) + 1) * 4.0)
    score += 8.0 if record.get("source_is_core") else 0.0
    score += 2.0 if record.get("doi") else 0.0
    score += 2.0 if record.get("abstract") else 0.0
    score += 2.0 if record.get("institutions") else 0.0
    if normalize_title(record.get("title")) == normalize_title(REFERENCE_TITLE):
        score += 100.0
    return score


def _dedup_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    openalex_id = normalize_space(record.get("openalex_id") or record.get("id")).lower()
    doi = normalize_doi(record.get("doi"))
    title = normalize_title(record.get("title"))
    if openalex_id:
        keys.add(f"openalex:{openalex_id}")
    if doi:
        keys.add(f"doi:{doi}")
    if title:
        keys.add(f"title:{title}")
    return keys


def collect_expansion(
    originals: list[dict[str, Any]],
    output_dir: Path,
    per_page: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_dir = output_dir / "raw_search_results"
    raw_dir.mkdir(parents=True, exist_ok=True)
    original_keys = set().union(*(_dedup_keys(record) for record in originals)) if originals else set()
    candidates_by_direction: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    search_log: list[dict[str, Any]] = []

    for direction_code, spec in FUTURE_DIRECTIONS.items():
        for query_index, query in enumerate(spec["queries"], start=1):
            payload = fetch_openalex(query, per_page=per_page)
            raw_path = raw_dir / f"{direction_code.lower()}_{query_index:02d}.json"
            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            accepted = 0
            duplicate_original = 0
            rejected_scope = 0
            rejected_direction = 0
            for raw in payload.get("results") or []:
                record = openalex_to_record(raw, direction_code, query)
                if (
                    normalize_title(record.get("title")) == normalize_title(REFERENCE_TITLE)
                    and direction_code != "M01"
                ):
                    rejected_direction += 1
                    continue
                if record["is_retracted"] or not record["title"] or not record["authors"] or not record["source_name"]:
                    rejected_scope += 1
                    continue
                keys = _dedup_keys(record)
                if keys & original_keys:
                    duplicate_original += 1
                    continue
                if not record["classification"]["in_scope"]:
                    rejected_scope += 1
                    continue
                direction_score = _direction_match_score(record, direction_code)
                if direction_score < 0:
                    rejected_direction += 1
                    continue
                record["selection_score"] = round(direction_score, 3)
                canonical = min(keys) if keys else f"hash:{hashlib.sha1(record['title'].encode()).hexdigest()}"
                previous = candidates_by_direction[direction_code].get(canonical)
                if previous is None or record["selection_score"] > previous["selection_score"]:
                    candidates_by_direction[direction_code][canonical] = record
                accepted += 1
            search_log.append(
                {
                    "direction_code": direction_code,
                    "direction_label": spec["label"],
                    "query": query,
                    "openalex_count": (payload.get("meta") or {}).get("count"),
                    "returned": len(payload.get("results") or []),
                    "accepted_before_cross_direction_dedup": accepted,
                    "duplicate_of_original": duplicate_original,
                    "rejected_scope_or_metadata": rejected_scope,
                    "rejected_direction_mismatch": rejected_direction,
                    "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            )

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set(original_keys)
    for direction_code, spec in FUTURE_DIRECTIONS.items():
        ranked = sorted(
            candidates_by_direction[direction_code].values(),
            key=lambda record: (
                -float(record.get("selection_score") or 0.0),
                -int(record.get("cited_by_count") or 0),
                normalize_title(record.get("title")),
            ),
        )
        count = 0
        for record in ranked:
            keys = _dedup_keys(record)
            if keys & selected_keys:
                continue
            record = dict(record)
            record["corpus_id"] = f"expanded-{len(selected) + 1:03d}"
            selected.append(record)
            selected_keys.update(keys)
            count += 1
            if count >= int(spec["target"]):
                break
        search_log.append(
            {
                "direction_code": direction_code,
                "direction_label": spec["label"],
                "selection_target": int(spec["target"]),
                "selected_unique": count,
                "status": "complete" if count == int(spec["target"]) else "shortfall",
            }
        )
    return selected, search_log


def standardized_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    year = record.get("publication_year") or record.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    return {
        "corpus_id": record.get("corpus_id") or f"record-{index:03d}",
        "record_origin": record.get("record_origin") or "original_150",
        "title": normalize_space(record.get("title")),
        "publication_year": year,
        "work_type": normalize_space(record.get("work_type") or record.get("type")) or "article",
        "source_name": normalize_space(record.get("source_name") or record.get("journal")),
        "source_type": normalize_space(record.get("source_type")),
        "source_is_core": bool(record.get("source_is_core")),
        "openalex_id": normalize_space(record.get("openalex_id")),
        "doi": normalize_doi(record.get("doi")),
        "landing_page_url": normalize_space(record.get("landing_page_url")),
        "oa_url": normalize_space(record.get("oa_url")),
        "pdf_url": normalize_space(record.get("pdf_url")),
        "is_oa": bool(record.get("is_oa")),
        "oa_status": normalize_space(record.get("oa_status")),
        "is_retracted": bool(record.get("is_retracted")),
        "cited_by_count": int(record.get("cited_by_count") or 0),
        "authors": split_values(record.get("authors")),
        "institutions": split_values(record.get("institutions")),
        "countries": split_values(record.get("countries")),
        "authorships": record.get("authorships") or [],
        "concepts": split_values(record.get("concepts")),
        "keywords": split_values(record.get("keywords")),
        "abstract": normalize_space(record.get("abstract")),
        "coverage": record.get("coverage") or _coverage(record),
        "expansion_direction_code": record.get("expansion_direction_code"),
        "expansion_direction_label": record.get("expansion_direction_label"),
        "matched_query": normalize_space(record.get("matched_query")),
        "selection_score": record.get("selection_score"),
        "manual_review_reason": normalize_space(record.get("manual_review_reason")),
        "classification": record.get("classification") or classify_record(record),
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = (
        "corpus_id",
        "record_origin",
        "title",
        "publication_year",
        "work_type",
        "source_name",
        "doi",
        "openalex_id",
        "authors",
        "institutions",
        "countries",
        "cited_by_count",
        "coverage",
        "primary_topic_code",
        "primary_topic_label",
        "secondary_topic_codes",
        "future_direction_codes",
        "classification_confidence",
        "in_scope",
        "expansion_direction_code",
        "expansion_direction_label",
        "manual_review_reason",
        "matched_query",
        "selection_score",
        "oa_url",
        "pdf_url",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            classification = record.get("classification") or {}
            writer.writerow(
                {
                    "corpus_id": record.get("corpus_id"),
                    "record_origin": record.get("record_origin"),
                    "title": record.get("title"),
                    "publication_year": record.get("publication_year"),
                    "work_type": classification.get("work_type_normalized") or record.get("work_type"),
                    "source_name": record.get("source_name"),
                    "doi": record.get("doi"),
                    "openalex_id": record.get("openalex_id"),
                    "authors": "; ".join(record.get("authors") or []),
                    "institutions": "; ".join(record.get("institutions") or []),
                    "countries": "; ".join(record.get("countries") or []),
                    "cited_by_count": record.get("cited_by_count"),
                    "coverage": record.get("coverage"),
                    "primary_topic_code": classification.get("primary_topic_code"),
                    "primary_topic_label": classification.get("primary_topic_label"),
                    "secondary_topic_codes": "; ".join(classification.get("secondary_topic_codes") or []),
                    "future_direction_codes": "; ".join(classification.get("future_direction_codes") or []),
                    "classification_confidence": classification.get("confidence"),
                    "in_scope": classification.get("in_scope"),
                    "expansion_direction_code": record.get("expansion_direction_code"),
                    "expansion_direction_label": record.get("expansion_direction_label"),
                    "manual_review_reason": record.get("manual_review_reason"),
                    "matched_query": record.get("matched_query"),
                    "selection_score": record.get("selection_score"),
                    "oa_url": record.get("oa_url"),
                    "pdf_url": record.get("pdf_url"),
                }
            )


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    topic_counts = Counter()
    future_counts = Counter()
    confidence_counts = Counter()
    coverage_counts = Counter()
    origin_counts = Counter()
    country_counts = Counter()
    institution_coverage = 0
    in_scope = 0
    for record in records:
        classification = record.get("classification") or {}
        topic_counts[classification.get("primary_topic_code") or "<missing>"] += 1
        for code in classification.get("future_direction_codes") or []:
            future_counts[code] += 1
        confidence_counts[classification.get("confidence") or "<missing>"] += 1
        coverage_counts[record.get("coverage") or "<missing>"] += 1
        origin_counts[record.get("record_origin") or "<missing>"] += 1
        if classification.get("in_scope"):
            in_scope += 1
        if record.get("institutions"):
            institution_coverage += 1
        for country in record.get("countries") or []:
            country_counts[country] += 1
    return {
        "total_records": len(records),
        "in_scope_records": in_scope,
        "out_of_scope_records": len(records) - in_scope,
        "primary_topic_counts": dict(sorted(topic_counts.items())),
        "primary_topic_labels": {
            code: (TOPIC_BY_CODE[code].label if code in TOPIC_BY_CODE else OTHER_AIED["label"] if code == "O01" else OUT_OF_SCOPE["label"] if code == "X00" else code)
            for code in sorted(topic_counts)
        },
        "future_direction_counts": dict(sorted(future_counts.items())),
        "future_direction_labels": {code: FUTURE_DIRECTIONS[code]["label"] for code in sorted(future_counts)},
        "classification_confidence": dict(sorted(confidence_counts.items())),
        "coverage": dict(sorted(coverage_counts.items())),
        "record_origins": dict(sorted(origin_counts.items())),
        "records_with_institutions": institution_coverage,
        "institution_coverage_ratio": round(institution_coverage / len(records), 4) if records else 0.0,
        "country_occurrences": dict(country_counts.most_common()),
    }


def taxonomy_payload() -> dict[str, Any]:
    return {
        "reference_review": REFERENCE_TITLE,
        "topics": [
            {
                "code": rule.code,
                "label": rule.label,
                "reference_group": rule.reference_group,
                "patterns": list(rule.patterns),
            }
            for rule in TOPIC_RULES
        ]
        + [OTHER_AIED, OUT_OF_SCOPE],
        "future_directions": {
            code: {
                "label": spec["label"],
                "queries": list(spec["queries"]),
                "target": spec["target"],
                "selection_title_patterns": list(spec.get("title_patterns", ())),
                "allowed_topic_codes": list(spec.get("allowed_topic_codes", ())),
            }
            for code, spec in FUTURE_DIRECTIONS.items()
        },
        "classification_notes": [
            "Primary topics are selected by weighted matches in titles, abstracts, OpenAlex topics, keywords, and original query labels.",
            "Unmatched records are assigned to O01 rather than to Generative AI.",
            "Records without both educational and AI signals are assigned to X00 for manual review.",
            "Missing years remain null and are never imputed to 2000.",
            "Topic labels are model-assisted deterministic codes, not author-supplied keywords.",
        ],
    }


def build_manual_review_queue(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for record in records:
        classification = record.get("classification") or {}
        if not classification.get("in_scope"):
            reason = "out_of_scope_or_insufficient_aied_evidence"
        elif classification.get("confidence") == "low":
            reason = "low_confidence_topic_assignment"
        else:
            continue
        item = dict(record)
        item["manual_review_reason"] = reason
        queue.append(item)
    return queue


def validate_corpus(
    originals: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    expanded: list[dict[str, Any]],
) -> dict[str, Any]:
    target_total = sum(int(spec["target"]) for spec in FUTURE_DIRECTIONS.values())
    direction_counts = Counter(record.get("expansion_direction_code") for record in selected)
    expected_direction_counts = {code: int(spec["target"]) for code, spec in FUTURE_DIRECTIONS.items()}

    original_keys = set().union(*(_dedup_keys(record) for record in originals)) if originals else set()
    selected_keys: set[str] = set()
    cross_corpus_duplicates: list[str] = []
    within_expansion_duplicates: list[str] = []
    for record in selected:
        keys = _dedup_keys(record)
        if keys & original_keys:
            cross_corpus_duplicates.append(record.get("corpus_id") or record.get("title") or "<unknown>")
        if keys & selected_keys:
            within_expansion_duplicates.append(record.get("corpus_id") or record.get("title") or "<unknown>")
        selected_keys.update(keys)

    missing_required_metadata = [
        record.get("corpus_id") or "<unknown>"
        for record in selected
        if not record.get("title") or not record.get("authors") or not record.get("source_name")
    ]
    reference_hits = [
        record
        for record in selected
        if normalize_title(record.get("title")) == normalize_title(REFERENCE_TITLE)
        and record.get("expansion_direction_code") == "M01"
    ]

    checks = {
        "original_count_is_150": len(originals) == 150,
        "expansion_target_met": len(selected) == target_total,
        "expanded_count_is_additive": len(expanded) == len(originals) + len(selected),
        "direction_targets_met": dict(sorted(direction_counts.items())) == expected_direction_counts,
        "no_cross_corpus_duplicates": not cross_corpus_duplicates,
        "no_within_expansion_duplicates": not within_expansion_duplicates,
        "all_additions_in_scope": all((record.get("classification") or {}).get("in_scope") for record in selected),
        "no_retracted_additions": not any(record.get("is_retracted") for record in selected),
        "required_metadata_present": not missing_required_metadata,
        "reference_review_in_m01": len(reference_hits) == 1,
    }
    errors = [name for name, passed in checks.items() if not passed]
    additions_with_institutions = sum(bool(record.get("institutions")) for record in selected)
    additions_with_abstracts = sum(bool(record.get("abstract")) for record in selected)
    additions_with_pdf_urls = sum(bool(record.get("pdf_url")) for record in selected)
    return {
        "passed": not errors,
        "checks": checks,
        "errors": errors,
        "metrics": {
            "original_records": len(originals),
            "selected_additions": len(selected),
            "expanded_records": len(expanded),
            "direction_counts": dict(sorted(direction_counts.items())),
            "additions_with_institutions": additions_with_institutions,
            "additions_from_core_sources": sum(bool(record.get("source_is_core")) for record in selected),
            "additions_with_abstracts": additions_with_abstracts,
            "additions_with_pdf_urls": additions_with_pdf_urls,
            "additions_with_dois": sum(bool(record.get("doi")) for record in selected),
            "cross_corpus_duplicate_ids": cross_corpus_duplicates,
            "within_expansion_duplicate_ids": within_expansion_duplicates,
            "missing_required_metadata_ids": missing_required_metadata,
        },
    }


def write_report(
    path: Path,
    original_summary: dict[str, Any],
    expanded_summary: dict[str, Any],
    selected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
    validation: dict[str, Any],
) -> None:
    additions_by_direction = Counter(record.get("expansion_direction_code") for record in selected)
    lines = [
        "# AIEd Corpus Classification and Reference-Aligned Expansion",
        "",
        f"Reference review: *{REFERENCE_TITLE}*.",
        "",
        "## Corpus outcomes",
        "",
        f"- Original records classified: {original_summary['total_records']}",
        f"- Original in-scope records: {original_summary['in_scope_records']}",
        f"- Original out-of-scope/manual-review records: {original_summary['out_of_scope_records']}",
        f"- Low-confidence or out-of-scope review queue: {len(manual_review)}",
        f"- Unique records added from OpenAlex: {len(selected)}",
        f"- Expanded corpus size: {expanded_summary['total_records']}",
        f"- Expanded records with institution data: {expanded_summary['records_with_institutions']}",
        f"- Corpus validation gate: {'PASS' if validation['passed'] else 'FAIL'}",
        "",
        "## Added records by reference direction",
        "",
        "| Code | Direction | Added | Target |",
        "|---|---|---:|---:|",
    ]
    for code, spec in FUTURE_DIRECTIONS.items():
        lines.append(f"| {code} | {spec['label']} | {additions_by_direction.get(code, 0)} | {spec['target']} |")
    lines.extend(
        [
            "",
            "## Original primary-topic distribution",
            "",
            "| Code | Topic | Records |",
            "|---|---|---:|",
        ]
    )
    for code, count in sorted(original_summary["primary_topic_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {code} | {original_summary['primary_topic_labels'][code]} | {count} |")
    lines.extend(
        [
            "",
            "## Evidence and access limitations",
            "",
            "- OpenAlex expansion is a public-index approximation, not a complete WoS, Scopus, or ERIC export.",
            "- Topic labels are deterministic model-assisted coding and require manual review for low-confidence records.",
            "- Added records include OpenAlex institution/country metadata when present; absence does not imply no affiliation.",
            "- PDF URLs are retained when OpenAlex reports an open-access location, but full-text availability was not assumed from metadata alone.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Original corpus JSON.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Independent output directory.")
    parser.add_argument("--per-page", type=int, default=100, help="OpenAlex results fetched per query.")
    parser.add_argument("--classify-only", action="store_true", help="Skip OpenAlex expansion.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    originals_raw = load_records(args.input)
    originals_classified_raw = classify_original(originals_raw)
    originals = [standardized_record(record, index) for index, record in enumerate(originals_classified_raw, start=1)]

    selected: list[dict[str, Any]] = []
    search_log: list[dict[str, Any]] = []
    if not args.classify_only:
        selected_raw, search_log = collect_expansion(originals_raw, args.output_dir, args.per_page)
        selected = [standardized_record(record, index) for index, record in enumerate(selected_raw, start=1)]

    expanded = originals + selected
    taxonomy = taxonomy_payload()
    original_summary = summarize(originals)
    expanded_summary = summarize(expanded)
    manual_review = build_manual_review_queue(originals)
    validation = validate_corpus(originals, selected, expanded) if not args.classify_only else {
        "passed": True,
        "checks": {"classification_only": True},
        "errors": [],
        "metrics": {"original_records": len(originals)},
    }

    (args.output_dir / "taxonomy.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "classified_150.json").write_text(json.dumps(originals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output_dir / "classified_150.csv", originals)
    (args.output_dir / "classification_summary.json").write_text(json.dumps(original_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "manual_review_queue.json").write_text(json.dumps(manual_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output_dir / "manual_review_queue.csv", manual_review)
    (args.output_dir / "expansion_candidates.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output_dir / "expansion_candidates.csv", selected)
    (args.output_dir / "expansion_search_log.json").write_text(json.dumps(search_log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "expanded_corpus.json").write_text(json.dumps(expanded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output_dir / "expanded_corpus.csv", expanded)
    (args.output_dir / "expanded_summary.json").write_text(json.dumps(expanded_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "corpus_validation.report.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(
        args.output_dir / "classification_expansion_report.md",
        original_summary,
        expanded_summary,
        selected,
        manual_review,
        validation,
    )

    print(json.dumps({"original": original_summary, "expanded": expanded_summary, "added": len(selected), "manual_review": len(manual_review), "validation": validation}, ensure_ascii=False, indent=2))
    return 0 if validation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
