"""Citation validation for generated outputs."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple, Pattern
from urllib.parse import urlparse, quote

logger = logging.getLogger(__name__)


@dataclass
class CitationFormat:
    """Configuration for a citation format style."""
    name: str
    in_text_pattern: str
    reference_pattern: str
    author_year_separator: str
    multiple_authors_separator: str
    et_al_threshold: int
    url_required: bool = False
    doi_preferred: bool = True
    access_date_required: bool = False


@dataclass
class Citation:
    """Represents a parsed citation."""
    raw_text: str
    authors: List[str]
    year: Optional[int]
    title: Optional[str]
    source: Optional[str]
    doi: Optional[str]
    url: Optional[str]
    pages: Optional[str]
    volume: Optional[str]
    issue: Optional[str]
    publisher: Optional[str]
    citation_type: str
    format_style: str
    start_pos: int
    end_pos: int
    is_in_text: bool
    confidence: float = 1.0


@dataclass
class CitationIssue:
    """Represents a citation-related issue."""
    issue_type: str
    description: str
    severity: str
    citation_text: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class CitationStatistics:
    """Statistics about citations in content."""
    total_citations: int = 0
    in_text_citations: int = 0
    reference_citations: int = 0
    unique_sources: int = 0
    citation_density: float = 0.0
    missing_citations: int = 0
    inconsistent_citations: int = 0
    format_breakdown: Dict[str, int] = field(default_factory=dict)
    year_range: Optional[Tuple[int, int]] = None
    most_cited_authors: List[Tuple[str, int]] = field(default_factory=list)
    citation_types: Dict[str, int] = field(default_factory=dict)
    doi_count: int = 0
    url_count: int = 0
    issues: List[CitationIssue] = field(default_factory=list)


CITATION_FORMATS: Dict[str, CitationFormat] = {
    "apa": CitationFormat(
        name="APA",
        in_text_pattern=r"\([^)]*?\d{4}[^)]*?\)",
        reference_pattern=r"^[A-Z][^,]+,\s*[A-Z]\.(?:\s*[A-Z]\.)*\s*\(?\d{4}\)?",
        author_year_separator=", ",
        multiple_authors_separator=", ",
        et_al_threshold=3,
        url_required=False,
        doi_preferred=True,
        access_date_required=False,
    ),
    "mla": CitationFormat(
        name="MLA",
        in_text_pattern=r"\([^)]*?\d+[^)]*?\)",
        reference_pattern=r"^[A-Z][^,]+,\s*[A-Z][^.]*\.",
        author_year_separator=" ",
        multiple_authors_separator=" and ",
        et_al_threshold=3,
        url_required=False,
        doi_preferred=False,
        access_date_required=True,
    ),
    "chicago": CitationFormat(
        name="Chicago",
        in_text_pattern=r"(?:\([^)]*?\d{4}[^)]*?\)|\[\d+\])",
        reference_pattern=r"^\d+\.\s+[A-Z]",
        author_year_separator=" ",
        multiple_authors_separator=" and ",
        et_al_threshold=4,
        url_required=False,
        doi_preferred=False,
        access_date_required=True,
    ),
    "ieee": CitationFormat(
        name="IEEE",
        in_text_pattern=r"\[\d+(?:[,-]\d+)*\]",
        reference_pattern=r"^\[\d+\]\s+",
        author_year_separator=", ",
        multiple_authors_separator=", ",
        et_al_threshold=6,
        url_required=False,
        doi_preferred=False,
        access_date_required=True,
    ),
    "harvard": CitationFormat(
        name="Harvard",
        in_text_pattern=r"\([^)]*?\d{4}[^)]*?\)",
        reference_pattern=r"^[A-Z][^,]+,\s*[A-Z]\.\s*\(?\d{4}\)?",
        author_year_separator=", ",
        multiple_authors_separator=", ",
        et_al_threshold=3,
        url_required=False,
        doi_preferred=True,
        access_date_required=False,
    ),
}


DOI_PATTERN = re.compile(r"\b(10\.\d{4,}/[^\s,;)\]]+)\b")
URL_PATTERN = re.compile(r"https?://[^\s,;)\]}>]+")
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20[0-2]\d)\b")
AUTHOR_PATTERN = re.compile(r"([A-Z][a-z]+(?:\s+[A-Z]\.)*)")
PAGE_PATTERN = re.compile(r"(?:pp?\.?\s*)?(\d+(?:–\d+)?)", re.UNICODE)
VOLUME_PATTERN = re.compile(r"(?:Vol\.?\s*|volume\s+)(\d+)", re.IGNORECASE)
ISSUE_PATTERN = re.compile(r"(?:No\.?\s*|issue\s+)(\d+)", re.IGNORECASE)
TRANSITION_WORDS = {
    "according to", "as noted by", "as stated by", "as reported by",
    "as described by", "as shown by", "suggests that", "argues that",
    "claims that", "states that", "notes that", "found that",
    "demonstrated that", "observed that", "reported that",
    "in their study", "in their work", "in their research",
    "per", "see", "cf", "e.g.", "i.e.",
}
ET_AL_PATTERN = re.compile(r"\bet\s*al\.?\b", re.IGNORECASE)
IBID_PATTERN = re.compile(r"\bibid\.?\b", re.IGNORECASE)
OP_CIT_PATTERN = re.compile(r"\bop\.?\s*cit\.?\b", re.IGNORECASE)
LOC_CIT_PATTERN = re.compile(r"\bloc\.?\s*cit\.?\b", re.IGNORECASE)


class CitationValidator:
    """Validates citations in generated content across multiple formats."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.enabled_formats: Set[str] = set(
            self.config.get("enabled_formats", ["apa", "mla", "chicago", "ieee", "harvard"])
        )
        self.strict_mode: bool = self.config.get("strict_mode", False)
        self.min_citation_density: float = self.config.get("min_citation_density", 0.02)
        self.max_year_future_offset: int = self.config.get("max_year_future_offset", 2)
        self.check_url_accessibility: bool = self.config.get("check_url_accessibility", False)
        self.require_doi_for_journals: bool = self.config.get("require_doi_for_journals", False)
        self.validate_references_exist: bool = self.config.get("validate_references_exist", True)
        self.logger.info(
            "CitationValidator initialized with formats: %s",
            ", ".join(sorted(self.enabled_formats)),
        )

    def validate(self, content: str) -> Dict[str, Any]:
        """Validate all citations in content and return assessment."""
        self.logger.debug("Validating citations for content length: %d", len(content))
        citations = self.extract_all_citations(content)
        issues: List[CitationIssue] = []
        for citation in citations:
            citation_issues = self._validate_single_citation(citation)
            issues.extend(citation_issues)
        missing = self._detect_missing_citations(content, citations)
        issues.extend(missing)
        consistency_issues = self._check_consistency(citations)
        issues.extend(consistency_issues)
        bib_issues = self._validate_bibliography(content, citations)
        issues.extend(bib_issues)
        stats = self._compute_statistics(content, citations, issues)
        recommendation = self._generate_recommendations(issues)
        result: Dict[str, Any] = {
            "valid": len([i for i in issues if i.severity == "error"]) == 0,
            "citations": [self._citation_to_dict(c) for c in citations],
            "issues": [self._issue_to_dict(i) for i in issues],
            "statistics": self._stats_to_dict(stats),
            "recommendations": recommendation,
            "total_citations": len(citations),
            "total_issues": len(issues),
            "error_count": sum(1 for i in issues if i.severity == "error"),
            "warning_count": sum(1 for i in issues if i.severity == "warning"),
            "info_count": sum(1 for i in issues if i.severity == "info"),
        }
        self.logger.info(
            "Citation validation completed: valid=%s, citations=%d, issues=%d",
            result["valid"], result["total_citations"], result["total_issues"],
        )
        return result

    def extract_all_citations(self, content: str) -> List[Citation]:
        """Extract all citations from content."""
        citations: List[Citation] = []
        seen_spans: Set[Tuple[int, int]] = set()
        for fmt_name in self.enabled_formats:
            if fmt_name not in CITATION_FORMATS:
                continue
            fmt = CITATION_FORMATS[fmt_name]
            for match in re.finditer(fmt.in_text_pattern, content):
                span = (match.start(), match.end())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                citation = self._parse_citation(match.group(), fmt_name, content, match.start(), match.end(), True)
                citations.append(citation)
            lines = content.split("\n")
            ref_start = self._find_reference_section(content)
            if ref_start is not None:
                ref_text = content[ref_start:]
                ref_lines = ref_text.split("\n")
                for i, line in enumerate(ref_lines):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    abs_pos = ref_start + sum(len(l) + 1 for l in ref_lines[:i])
                    citation = self._parse_reference_line(stripped, fmt_name, abs_pos)
                    if citation is not None:
                        c_span = (citation.start_pos, citation.end_pos)
                        if c_span not in seen_spans:
                            seen_spans.add(c_span)
                            citations.append(citation)
        citations.sort(key=lambda c: c.start_pos)
        return citations

    def _find_reference_section(self, content: str) -> Optional[int]:
        """Find the start of the reference/bibliography section."""
        patterns = [
            r"^#\s*(?:References|Bibliography|Works Cited|Sources)\s*$",
            r"^References$",
            r"^Bibliography$",
            r"^Works Cited$",
            r"^Sources$",
            r"^REFERENCES$",
            r"^BIBLIOGRAPHY$",
            r"^WORKS CITED$",
        ]
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            for pat in patterns:
                if re.match(pat, stripped):
                    abs_pos = sum(len(l) + 1 for l in lines[:i])
                    return abs_pos
        return None

    def _parse_citation(
        self, text: str, fmt_name: str, content: str, start: int, end: int, is_in_text: bool
    ) -> Citation:
        """Parse a single citation from text."""
        authors = self._extract_authors(text)
        year = self._extract_year(text)
        doi = self._extract_doi(text)
        url = self._extract_url(text)
        pages = self._extract_pages(text)
        volume = self._extract_volume(text)
        issue = self._extract_issue(text)
        citation_type = self._classify_citation_type(text, authors, year, doi, url)
        return Citation(
            raw_text=text,
            authors=authors,
            year=year,
            title=None,
            source=None,
            doi=doi,
            url=url,
            pages=pages,
            volume=volume,
            issue=issue,
            publisher=None,
            citation_type=citation_type,
            format_style=fmt_name,
            start_pos=start,
            end_pos=end,
            is_in_text=is_in_text,
        )

    def _parse_reference_line(self, line: str, fmt_name: str, abs_pos: int) -> Optional[Citation]:
        """Parse a single reference/bibliography line."""
        fmt = CITATION_FORMATS.get(fmt_name)
        if fmt is None:
            return None
        if not re.match(fmt.reference_pattern, line):
            return None
        authors = self._extract_authors(line)
        year = self._extract_year(line)
        doi = self._extract_doi(line)
        url = self._extract_url(line)
        pages = self._extract_pages(line)
        volume = self._extract_volume(line)
        issue = self._extract_issue(line)
        title = self._extract_title(line)
        source = self._extract_source(line)
        publisher = self._extract_publisher(line)
        citation_type = self._classify_citation_type(line, authors, year, doi, url)
        return Citation(
            raw_text=line,
            authors=authors,
            year=year,
            title=title,
            source=source,
            doi=doi,
            url=url,
            pages=pages,
            volume=volume,
            issue=issue,
            publisher=publisher,
            citation_type=citation_type,
            format_style=fmt_name,
            start_pos=abs_pos,
            end_pos=abs_pos + len(line),
            is_in_text=False,
        )

    def _extract_authors(self, text: str) -> List[str]:
        """Extract author names from citation text."""
        authors: List[str] = []
        matches = AUTHOR_PATTERN.findall(text)
        for m in matches:
            m = m.strip()
            if m and len(m) > 1:
                authors.append(m)
        corporate_match = re.search(r"([A-Z][A-Z\s&]+)(?=\s*\(|\s*\d{4}|\s*\.)", text)
        if corporate_match:
            corp = corporate_match.group(1).strip()
            if corp and len(corp) > 3:
                authors.append(corp)
        if not authors:
            org_match = re.search(r"\(([A-Z][A-Z\s]+)\)", text)
            if org_match:
                authors.append(org_match.group(1).strip())
        return authors

    def _extract_year(self, text: str) -> Optional[int]:
        """Extract publication year from citation text."""
        matches = YEAR_PATTERN.findall(text)
        if not matches:
            return None
        current_year = datetime.now().year
        max_future = current_year + self.max_year_future_offset
        for year_str in matches:
            year = int(year_str)
            if 1900 <= year <= max_future:
                return year
        return None

    def _extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from citation text."""
        match = DOI_PATTERN.search(text)
        if match:
            doi = match.group(1).rstrip(".,;:)")
            return doi
        return None

    def _extract_url(self, text: str) -> Optional[str]:
        """Extract URL from citation text."""
        match = URL_PATTERN.search(text)
        if match:
            return match.group(0).rstrip(".,;:)>")
        return None

    def _extract_pages(self, text: str) -> Optional[str]:
        """Extract page numbers from citation text."""
        match = PAGE_PATTERN.search(text)
        if match:
            return match.group(1)
        return None

    def _extract_volume(self, text: str) -> Optional[str]:
        """Extract volume number from citation text."""
        match = VOLUME_PATTERN.search(text)
        if match:
            return match.group(1)
        return None

    def _extract_issue(self, text: str) -> Optional[str]:
        """Extract issue number from citation text."""
        match = ISSUE_PATTERN.search(text)
        if match:
            return match.group(1)
        return None

    def _extract_title(self, text: str) -> Optional[str]:
        """Extract title from reference line."""
        patterns = [
            r'[".]?\s*"([^"]+)"',
            r"['.]?\s*'([^']+)'",
            r"(?:^[^.]*?\.\s*)([A-Z][^.;]+)",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                title = match.group(1).strip()
                if len(title) > 5:
                    return title
        return None

    def _extract_source(self, text: str) -> Optional[str]:
        """Extract source/journal name from reference line."""
        patterns = [
            r"(?:In\s+)?([A-Z][A-Za-z\s]+?)(?:\s*,\s*\d+|\s*Vol\.|\s*\(?\d{4}\))",
            r"([A-Z][A-Za-z\s]+?)\s+\d+",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                src = match.group(1).strip()
                if src and len(src) > 3 and " " in src:
                    return src
        return None

    def _extract_publisher(self, text: str) -> Optional[str]:
        """Extract publisher from reference line."""
        patterns = [
            r"(?:New York|London|Oxford|Cambridge|Paris|Berlin|Tokyo)\s*:\s*([^,.;]+)",
            r"published by\s+([^,.;]+)",
            r"Press(?:,?\s*([^,.;]+))?",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                pub = match.group(1).strip() if match.lastindex and match.group(1) else match.group(0).strip()
                if pub and len(pub) > 2:
                    return pub
        return None

    def _classify_citation_type(self, text: str, authors: List[str], year: Optional[int], doi: Optional[str], url: Optional[str]) -> str:
        """Classify the type of source being cited."""
        journal_indicators = ["journal", "review", "quarterly", "transaction", "proceedings", "letter", "annals"]
        book_indicators = ["press", "publisher", "books", "edition"]
        conference_indicators = ["conference", "symposium", "workshop", "proceedings"]
        report_indicators = ["report", "technical report", "working paper", "white paper"]
        thesis_indicators = ["thesis", "dissertation", "phd", "master"]
        text_lower = text.lower()
        for ind in conference_indicators:
            if ind in text_lower:
                return "conference"
        for ind in journal_indicators:
            if ind in text_lower:
                return "journal"
        for ind in book_indicators:
            if ind in text_lower:
                return "book"
        for ind in report_indicators:
            if ind in text_lower:
                return "report"
        for ind in thesis_indicators:
            if ind in text_lower:
                return "thesis"
        if url and "arxiv" in text_lower:
            return "preprint"
        if doi is not None:
            return "journal"
        if url is not None:
            return "web"
        if authors and year:
            return "unknown"
        return "unknown"

    def _validate_single_citation(self, citation: Citation) -> List[CitationIssue]:
        """Validate a single citation for correctness."""
        issues: List[CitationIssue] = []
        if citation.year is None:
            issues.append(CitationIssue(
                issue_type="missing_year",
                description=f"Citation missing publication year: {citation.raw_text[:80]}",
                severity="error",
                citation_text=citation.raw_text,
                suggestion="Add the publication year to the citation.",
            ))
        elif citation.year > datetime.now().year + self.max_year_future_offset:
            issues.append(CitationIssue(
                issue_type="future_year",
                description=f"Citation has a year ({citation.year}) in the future beyond allowed offset",
                severity="error",
                citation_text=citation.raw_text,
                suggestion="Verify the publication year is correct.",
            ))
        elif citation.year < 1800:
            issues.append(CitationIssue(
                issue_type="implausible_year",
                description=f"Citation year ({citation.year}) seems implausibly old",
                severity="warning",
                citation_text=citation.raw_text,
                suggestion="Verify the publication year is correct.",
            ))
        if not citation.authors and citation.citation_type != "web":
            issues.append(CitationIssue(
                issue_type="missing_author",
                description=f"Citation missing author information: {citation.raw_text[:80]}",
                severity="error",
                citation_text=citation.raw_text,
                suggestion="Add author names to the citation.",
            ))
        if citation.citation_type in ("journal",) and citation.doi is None and self.require_doi_for_journals:
            issues.append(CitationIssue(
                issue_type="missing_doi",
                description=f"Journal citation missing DOI: {citation.raw_text[:80]}",
                severity="warning",
                citation_text=citation.raw_text,
                suggestion="Add a DOI for journal article citations.",
            ))
        if citation.url and not self._is_valid_url_structure(citation.url):
            issues.append(CitationIssue(
                issue_type="invalid_url",
                description=f"Citation URL appears malformed: {citation.url}",
                severity="error",
                citation_text=citation.raw_text,
                suggestion="Correct the URL format.",
            ))
        if citation.citation_type in ("journal", "book") and citation.pages == citation.volume == citation.issue is None:
            if citation.citation_type == "journal":
                issues.append(CitationIssue(
                    issue_type="missing_publication_details",
                    description=f"Journal citation missing volume/issue/pages: {citation.raw_text[:80]}",
                    severity="warning",
                    citation_text=citation.raw_text,
                    suggestion="Add volume, issue, and page numbers.",
                ))
        return issues

    def _is_valid_url_structure(self, url: str) -> bool:
        """Check if URL has valid structure."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            if not parsed.netloc or "." not in parsed.netloc:
                return False
            return True
        except Exception:
            return False

    def _detect_missing_citations(self, content: str, citations: List[Citation]) -> List[CitationIssue]:
        """Detect potentially missing citations."""
        issues: List[CitationIssue] = []
        sentences = re.split(r"(?<=[.!?])\s+", content)
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            has_citation = bool(re.search(r"\([^)]*\d{4}[^)]*\)|\[\d+\]", stripped))
            has_transition = any(t in stripped.lower() for t in TRANSITION_WORDS)
            if has_transition and not has_citation:
                issues.append(CitationIssue(
                    issue_type="missing_citation",
                    description=f"Sentence uses attribution language but may lack a citation",
                    severity="warning",
                    citation_text=stripped[:100],
                    suggestion="Add a citation to support the attributed claim.",
                ))
        ref_section_start = self._find_reference_section(content)
        if ref_section_start is not None:
            ref_text = content[ref_section_start:]
            ref_lines = [l.strip() for l in ref_text.split("\n") if l.strip()]
            in_text_citations = [c for c in citations if c.is_in_text]
            if in_text_citations and not ref_lines:
                issues.append(CitationIssue(
                    issue_type="empty_references",
                    description="In-text citations found but reference section is empty",
                    severity="error",
                    suggestion="Add corresponding reference entries for all in-text citations.",
                ))
            if self.validate_references_exist:
                for ic in in_text_citations:
                    matched = False
                    for rc in citations:
                        if not rc.is_in_text and rc.authors and ic.authors:
                            if any(a in rc.raw_text for a in ic.authors) and (
                                ic.year is None or rc.year == ic.year
                            ):
                                matched = True
                                break
                        elif not rc.is_in_text and ic.year and str(ic.year) in rc.raw_text:
                            matched = True
                            break
                    if not matched and self.strict_mode:
                        issues.append(CitationIssue(
                            issue_type="unmatched_citation",
                            description=f"In-text citation has no matching reference entry",
                            severity="warning",
                            citation_text=ic.raw_text,
                            suggestion="Add a corresponding reference entry.",
                        ))
        if not citations:
            issues.append(CitationIssue(
                issue_type="no_citations",
                description="No citations found in the content",
                severity="warning",
                suggestion="Add citations to support claims and assertions.",
            ))
        return issues

    def _check_consistency(self, citations: List[Citation]) -> List[CitationIssue]:
        """Check for citation consistency issues."""
        issues: List[CitationIssue] = []
        author_citation_map: Dict[str, List[Citation]] = {}
        for c in citations:
            for author in c.authors:
                author_key = author.lower().strip()
                if author_key not in author_citation_map:
                    author_citation_map[author_key] = []
                author_citation_map[author_key].append(c)
        for author, author_citations in author_citation_map.items():
            if len(author_citations) < 2:
                continue
            years = [c.year for c in author_citations if c.year is not None]
            if len(years) >= 2:
                min_year = min(years)
                max_year = max(years)
                if max_year - min_year > 60:
                    issues.append(CitationIssue(
                        issue_type="implausible_timespan",
                        description=f"Author '{author}' has citations spanning {max_year - min_year} years "
                                    f"({min_year}-{max_year}), which may indicate errors",
                        severity="warning",
                    ))
            formats = set(c.format_style for c in author_citations)
            if len(formats) > 1:
                issues.append(CitationIssue(
                    issue_type="inconsistent_format",
                    description=f"Author '{author}' cited in multiple formats: {', '.join(sorted(formats))}",
                    severity="warning",
                    suggestion="Use a consistent citation format throughout the document.",
                ))
        seen_dois: Dict[str, Citation] = {}
        for c in citations:
            if c.doi:
                doi_lower = c.doi.lower()
                if doi_lower in seen_dois:
                    prev = seen_dois[doi_lower]
                    if c.authors != prev.authors or c.year != prev.year:
                        issues.append(CitationIssue(
                            issue_type="duplicate_doi_inconsistency",
                            description=f"Same DOI {c.doi} cited with different author/year information",
                            severity="error",
                            citation_text=c.raw_text,
                        ))
                else:
                    seen_dois[doi_lower] = c
        for c in citations:
            if not c.is_in_text and c.citation_type == "web" and c.url is None:
                issues.append(CitationIssue(
                    issue_type="web_citation_no_url",
                    description="Web source citation missing URL",
                    severity="warning",
                    citation_text=c.raw_text[:80],
                    suggestion="Include the URL and access date for web sources.",
                ))
        for i, c1 in enumerate(citations):
            for c2 in citations[i + 1:]:
                if c1.is_in_text != c2.is_in_text:
                    continue
                if not c1.is_in_text and c1.raw_text == c2.raw_text:
                    issues.append(CitationIssue(
                        issue_type="duplicate_reference",
                        description="Duplicate reference entry found",
                        severity="warning",
                        citation_text=c1.raw_text[:80],
                        suggestion="Remove duplicate reference entry.",
                    ))
        return issues

    def _validate_bibliography(self, content: str, citations: List[Citation]) -> List[CitationIssue]:
        """Validate bibliography structure and formatting."""
        issues: List[CitationIssue] = []
        ref_start = self._find_reference_section(content)
        if ref_start is not None:
            ref_text = content[ref_start:]
            ref_entries = [l.strip() for l in ref_text.split("\n") if l.strip() and len(l.strip()) > 5]
            ref_citations = [c for c in citations if not c.is_in_text]
            if ref_entries and not ref_citations:
                issues.append(CitationIssue(
                    issue_type="orphan_references",
                    description="Reference section exists but no references were parsed",
                    severity="warning",
                    suggestion="Check reference formatting for compliance with citation style.",
                ))
            if ref_citations and not ref_entries:
                issues.append(CitationIssue(
                    issue_type="references_not_formatted",
                    description="Citations were parsed but reference section may be empty",
                    severity="error",
                    suggestion="Ensure references are properly formatted.",
                ))
        else:
            in_text = [c for c in citations if c.is_in_text]
            if in_text:
                issues.append(CitationIssue(
                    issue_type="missing_bibliography",
                    description="In-text citations found but no reference/bibliography section detected",
                    severity="error",
                    suggestion="Add a References or Bibliography section.",
                ))
        fmt_groups: Dict[str, List[Citation]] = {}
        for c in citations:
            if c.format_style not in fmt_groups:
                fmt_groups[c.format_style] = []
            fmt_groups[c.format_style].append(c)
        if len(fmt_groups) > 1:
            fmt_names = sorted(fmt_groups.keys())
            issues.append(CitationIssue(
                issue_type="mixed_formats",
                description=f"Multiple citation formats detected: {', '.join(fmt_names)}",
                severity="warning",
                suggestion="Use a single citation format for consistency.",
            ))
        return issues

    def _compute_statistics(self, content: str, citations: List[Citation], issues: List[CitationIssue]) -> CitationStatistics:
        """Compute citation statistics."""
        stats = CitationStatistics()
        stats.total_citations = len(citations)
        stats.in_text_citations = sum(1 for c in citations if c.is_in_text)
        stats.reference_citations = sum(1 for c in citations if not c.is_in_text)
        all_authors: Dict[str, int] = {}
        all_years: List[int] = []
        for c in citations:
            for a in c.authors:
                key = a.lower().strip()
                all_authors[key] = all_authors.get(key, 0) + 1
            stats.format_breakdown[c.format_style] = stats.format_breakdown.get(c.format_style, 0) + 1
            stats.citation_types[c.citation_type] = stats.citation_types.get(c.citation_type, 0) + 1
            if c.year:
                all_years.append(c.year)
            if c.doi:
                stats.doi_count += 1
            if c.url:
                stats.url_count += 1
        stats.unique_sources = len(
            set(
                (tuple(c.authors), c.year, c.title, c.doi)
                for c in citations
                if c.authors or c.doi
            )
        )
        words = content.split()
        if words and citations:
            stats.citation_density = round(len(citations) / len(words), 4)
        stats.missing_citations = sum(
            1 for i in issues if i.issue_type in ("missing_citation", "no_citations")
        )
        stats.inconsistent_citations = sum(
            1 for i in issues if i.issue_type in ("inconsistent_format", "mixed_formats")
        )
        if all_years:
            stats.year_range = (min(all_years), max(all_years))
        sorted_authors = sorted(all_authors.items(), key=lambda x: x[1], reverse=True)
        stats.most_cited_authors = sorted_authors[:10]
        stats.issues = issues
        return stats

    def _citation_to_dict(self, citation: Citation) -> Dict[str, Any]:
        """Convert Citation to dictionary."""
        return {
            "raw_text": citation.raw_text,
            "authors": citation.authors,
            "year": citation.year,
            "title": citation.title,
            "source": citation.source,
            "doi": citation.doi,
            "url": citation.url,
            "pages": citation.pages,
            "volume": citation.volume,
            "issue": citation.issue,
            "publisher": citation.publisher,
            "citation_type": citation.citation_type,
            "format_style": citation.format_style,
            "start_pos": citation.start_pos,
            "end_pos": citation.end_pos,
            "is_in_text": citation.is_in_text,
            "confidence": citation.confidence,
        }

    def _issue_to_dict(self, issue: CitationIssue) -> Dict[str, Any]:
        """Convert CitationIssue to dictionary."""
        return {
            "issue_type": issue.issue_type,
            "description": issue.description,
            "severity": issue.severity,
            "citation_text": issue.citation_text,
            "suggestion": issue.suggestion,
        }

    def _stats_to_dict(self, stats: CitationStatistics) -> Dict[str, Any]:
        """Convert CitationStatistics to dictionary."""
        return {
            "total_citations": stats.total_citations,
            "in_text_citations": stats.in_text_citations,
            "reference_citations": stats.reference_citations,
            "unique_sources": stats.unique_sources,
            "citation_density": stats.citation_density,
            "missing_citations": stats.missing_citations,
            "inconsistent_citations": stats.inconsistent_citations,
            "format_breakdown": stats.format_breakdown,
            "year_range": list(stats.year_range) if stats.year_range else None,
            "most_cited_authors": [
                {"name": name, "count": count}
                for name, count in stats.most_cited_authors
            ],
            "citation_types": stats.citation_types,
            "doi_count": stats.doi_count,
            "url_count": stats.url_count,
            "issue_count": len(stats.issues),
        }

    def _generate_recommendations(self, issues: List[CitationIssue]) -> List[str]:
        """Generate recommendations based on citation issues."""
        recommendations_map: Dict[str, str] = {
            "missing_year": "Ensure all citations include the publication year.",
            "missing_author": "Add author names to all citations.",
            "missing_doi": "Include DOIs for journal article citations when available.",
            "invalid_url": "Verify all URLs are correctly formatted and accessible.",
            "missing_citation": "Add citations to support claims made with attribution language.",
            "empty_references": "Populate the reference section with complete entries.",
            "unmatched_citation": "Ensure every in-text citation has a matching reference entry.",
            "no_citations": "Consider adding citations to support the content's claims.",
            "mixed_formats": "Use a single citation format consistently throughout the document.",
            "duplicate_reference": "Remove duplicate reference entries.",
            "missing_bibliography": "Add a properly formatted reference section.",
            "inconsistent_format": "Maintain consistent citation formatting.",
        }
        seen_types: Set[str] = set()
        recommendations: List[str] = []
        for issue in issues:
            if issue.issue_type in seen_types:
                continue
            seen_types.add(issue.issue_type)
            rec = recommendations_map.get(issue.issue_type)
            if rec and rec not in recommendations:
                recommendations.append(rec)
        if not recommendations:
            recommendations.append("Citations appear well-formatted and consistent.")
        return recommendations

    def detect_style(self, content: str) -> Optional[str]:
        """Detect the primary citation style used in content."""
        scores: Dict[str, int] = {}
        for fmt_name, fmt in CITATION_FORMATS.items():
            in_text_matches = len(re.findall(fmt.in_text_pattern, content))
            if in_text_matches > 0:
                scores[fmt_name] = scores.get(fmt_name, 0) + in_text_matches * 2
            lines = content.split("\n")
            ref_start = self._find_reference_section(content)
            if ref_start is not None:
                ref_text = content[ref_start:]
                ref_matches = len(re.findall(fmt.reference_pattern, ref_text, re.MULTILINE))
                scores[fmt_name] = scores.get(fmt_name, 0) + ref_matches * 3
        if not scores:
            return None
        return max(scores, key=scores.get)

    def get_supported_styles(self) -> List[str]:
        """Get list of supported citation styles."""
        return sorted(CITATION_FORMATS.keys())

    def add_custom_format(self, name: str, config: Dict[str, Any]) -> None:
        """Add a custom citation format."""
        fmt = CitationFormat(
            name=name,
            in_text_pattern=config.get("in_text_pattern", r"\([^)]+\)"),
            reference_pattern=config.get("reference_pattern", r"^[A-Z]"),
            author_year_separator=config.get("author_year_separator", ", "),
            multiple_authors_separator=config.get("multiple_authors_separator", ", "),
            et_al_threshold=config.get("et_al_threshold", 3),
            url_required=config.get("url_required", False),
            doi_preferred=config.get("doi_preferred", False),
            access_date_required=config.get("access_date_required", False),
        )
        CITATION_FORMATS[name] = fmt
        self.enabled_formats.add(name)
        self.logger.info("Added custom citation format: %s", name)

    def validate_batch(self, contents: List[str]) -> List[Dict[str, Any]]:
        """Validate citations for multiple content items."""
        return [self.validate(content) for content in contents]

    def format_citation(self, citation: Citation, target_style: str = "apa") -> Optional[str]:
        """Reformat a citation to a different style."""
        if target_style not in CITATION_FORMATS:
            self.logger.warning("Unsupported target style: %s", target_style)
            return None
        if not citation.authors or citation.year is None:
            return citation.raw_text
        first_author = citation.authors[0]
        year_str = str(citation.year)
        if target_style == "apa":
            if len(citation.authors) == 1:
                return f"({first_author}, {year_str})"
            elif len(citation.authors) == 2:
                return f"({citation.authors[0]} & {citation.authors[1]}, {year_str})"
            else:
                return f"({first_author} et al., {year_str})"
        elif target_style == "mla":
            if len(citation.authors) == 1:
                return f"({first_author} {year_str})"
            elif len(citation.authors) == 2:
                return f"({citation.authors[0]} and {citation.authors[1]} {year_str})"
            else:
                return f"({first_author} et al. {year_str})"
        elif target_style == "chicago":
            if len(citation.authors) == 1:
                return f"({first_author} {year_str})"
            elif len(citation.authors) >= 3:
                return f"({first_author} et al. {year_str})"
            else:
                return f"({citation.authors[0]} and {citation.authors[1]} {year_str})"
        elif target_style == "ieee":
            return f"[{year_str}]"
        elif target_style == "harvard":
            if len(citation.authors) == 1:
                return f"({first_author}, {year_str})"
            elif len(citation.authors) >= 3:
                return f"({first_author} et al., {year_str})"
            else:
                return f"({citation.authors[0]} and {citation.authors[1]}, {year_str})"
        return citation.raw_text

    def calculate_citation_density(self, content: str) -> float:
        """Calculate citation density (citations per word)."""
        citations = self.extract_all_citations(content)
        words = content.split()
        if not words:
            return 0.0
        return round(len(citations) / len(words), 4)

    def find_unattributed_statements(self, content: str) -> List[str]:
        """Find sentences containing factual claims without citations."""
        unattributed: List[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", content)
        factual_indicators = [
            r"\bis\b",
            r"\bwas\b",
            r"\bare\b",
            r"\bwere\b",
            r"\bhas been\b",
            r"\bhave been\b",
            r"\bhad been\b",
            r"\bwill be\b",
            r"\bleads to\b",
            r"\bcauses\b",
            r"\bresults in\b",
            r"\bis known\b",
            r"\bis considered\b",
            r"\bis defined\b",
            r"\bconsists of\b",
            r"\bcontains\b",
            r"\bincludes\b",
            r"\bproves\b",
            r"\bdemonstrates\b",
            r"\bshows that\b",
            r"\bfound that\b",
            r"\b研究表明\b",
        ]
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped or len(stripped) < 20:
                continue
            has_citation = bool(re.search(r"\([^)]*\d{4}[^)]*\)|\[\d+\]", stripped))
            if has_citation:
                continue
            is_factual = False
            for indicator in factual_indicators:
                if re.search(indicator, stripped, re.IGNORECASE):
                    is_factual = True
                    break
            if is_factual:
                unattributed.append(stripped[:120])
        return unattributed

    def validate_doi_format(self, doi: str) -> bool:
        """Check if a DOI string has valid format."""
        match = DOI_PATTERN.match(doi)
        if not match:
            return False
        return len(match.group(0)) >= 8

    def extract_references_section(self, content: str) -> Optional[str]:
        """Extract the reference/bibliography section from content."""
        ref_start = self._find_reference_section(content)
        if ref_start is not None:
            return content[ref_start:]
        return None

    def count_citations_by_year(self, citations: List[Citation]) -> Dict[int, int]:
        """Count citations grouped by year."""
        year_counts: Dict[int, int] = {}
        for c in citations:
            if c.year is not None:
                year_counts[c.year] = year_counts.get(c.year, 0) + 1
        return dict(sorted(year_counts.items()))

    def get_author_citation_count(self, citations: List[Citation], author_name: str) -> int:
        """Get citation count for a specific author."""
        author_lower = author_name.lower().strip()
        return sum(
            1 for c in citations
            if any(a.lower().strip() == author_lower for a in c.authors)
        )
