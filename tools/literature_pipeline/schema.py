from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any


class AccessLevel(IntEnum):
    metadata_only = 0
    abstract_only = 1
    section_level = 2
    fulltext = 3


ACCESS_LEVELS = tuple(level.name for level in AccessLevel)

ACCESS_POLICIES: dict[str, tuple[str, ...]] = {
    "metadata_only": ("existence", "bibliographic", "publication_statistics"),
    "abstract_only": (
        "existence",
        "bibliographic",
        "publication_statistics",
        "background",
        "direction_existence",
        "research_question",
        "coarse_method",
        "abstract_finding",
    ),
    "section_level": (
        "existence",
        "bibliographic",
        "publication_statistics",
        "background",
        "direction_existence",
        "research_question",
        "coarse_method",
        "abstract_finding",
        "method_detail",
        "experimental_result",
        "performance_number",
        "limitation",
        "comparison",
        "future_direction",
    ),
    "fulltext": ("*",),
}


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


@dataclass
class Paper:
    paper_id: str
    work_id: str
    title: str
    authors: list[str]
    year: int | None = None
    source: str = ""
    citation_key: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    citation_count: int | None = None
    open_access: bool | None = None
    document_type: str = ""
    retrieval_sources: list[str] = field(default_factory=list)
    versions: list[dict[str, Any]] = field(default_factory=list)
    citation_version_paper_id: str = ""
    read_version_paper_id: str = ""
    screening_decision: str = "pending"
    screening_reasons: list[str] = field(default_factory=list)
    screening_scores: dict[str, float] = field(default_factory=dict)
    access_level: str = "metadata_only"
    accessed_content: list[str] = field(default_factory=list)
    fulltext_source: str = ""
    fulltext_format: str = ""
    allowed_claim_types: list[str] = field(default_factory=list)
    existence_verified: bool = False
    missing_fields: list[str] = field(default_factory=list)

    def finalize_policy(self) -> None:
        if self.access_level not in ACCESS_POLICIES:
            raise ValueError(f"invalid access_level: {self.access_level}")
        self.allowed_claim_types = list(ACCESS_POLICIES[self.access_level])
        required = {"title": self.title, "authors": self.authors}
        self.missing_fields = [name for name, value in required.items() if not value]

    def to_dict(self) -> dict[str, Any]:
        self.finalize_policy()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Paper":
        fields = cls.__dataclass_fields__
        paper = cls(**{key: val for key, val in value.items() if key in fields})
        paper.finalize_policy()
        return paper


@dataclass
class DocumentBlock:
    block_id: str
    kind: str
    text: str
    section: str = ""
    page: int | None = None
    paragraph: int | None = None
    table_id: str = ""
    caption: str = ""


@dataclass
class FulltextDocument:
    paper_id: str
    source_url: str
    source_format: str
    parser: str
    access_level: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[DocumentBlock] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        return result


@dataclass
class Evidence:
    evidence_id: str
    paper_id: str
    access_level: str
    relation: str
    source_section: str = ""
    page: int | None = None
    paragraph_id: str = ""
    table_id: str = ""
    excerpt: str = ""
    confidence: str = "medium"
    existence_verified: bool = False
    claim_supported: bool = False


@dataclass
class Claim:
    claim_id: str
    text: str
    claim_type: str
    strength: str
    research_questions: list[str]
    topics: list[str]
    evidence: list[Evidence]
    manuscript_text: str = ""
    citation_keys: list[str] = field(default_factory=list)
    support_status: str = "unverified"
    limitations: str = ""


@dataclass
class PaperCard:
    paper_id: str
    work_id: str
    title: str
    research_questions: list[str]
    methods: list[str]
    datasets: list[str]
    baselines: list[str]
    main_results: list[str]
    limitations: list[str]
    innovations: list[str]
    topic_tags: list[str]
    access_level: str
    evidence_ids: list[str]
    unresolved_fields: list[str] = field(default_factory=list)


@dataclass
class ThemeSynthesis:
    theme_id: str
    label: str
    paper_ids: list[str]
    consensus: list[str]
    disagreements: list[str]
    method_evolution: list[str]
    representative_papers: list[str]
    evidence_strength: str
    gaps: list[str]
    open_questions: list[str]
    claim_ids: list[str]
