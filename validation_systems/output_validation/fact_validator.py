"""Fact validation for generated outputs."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple, Pattern

logger = logging.getLogger(__name__)


@dataclass
class Fact:
    """Represents a single fact extracted from content."""
    text: str
    category: str
    confidence: float = 1.0
    source: Optional[str] = None
    entities: List[str] = field(default_factory=list)
    numerical_values: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    is_verified: bool = False
    verification_source: Optional[str] = None
    start_pos: int = 0
    end_pos: int = 0


@dataclass
class FactIssue:
    """An issue found during fact validation."""
    issue_type: str
    fact_text: str
    description: str
    severity: str
    confidence: float = 0.7
    suggestion: Optional[str] = None


@dataclass
class SourceCredibility:
    """Credibility assessment for a source."""
    source_name: str
    credibility_score: float = 0.5
    is_peer_reviewed: bool = False
    is_government: bool = False
    is_academic: bool = False
    is_news: bool = False
    is_primary: bool = False
    last_updated: Optional[datetime] = None
    citation_count: Optional[int] = None


NUMERICAL_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?(?:%|percent|thousand|million|billion|trillion)?", re.IGNORECASE)
DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b",
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20[0-2]\d|2030)\b")
ENTITY_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4}\b")
KNOWN_TRUE_FACTS: Dict[str, Set[str]] = {
    "sun": {"rises in the east", "sets in the west", "is a star", "nuclear fusion"},
    "earth": {"orbits the sun", "third planet", "rotates on its axis", "spherical"},
    "water": {"h2o", "freezes at 0", "boils at 100", "covers 71 percent"},
}
IMPLAUSIBLE_YEARS: Set[int] = set(range(1800, 2025))


class FactValidator:
    """Validates factual claims in generated content."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.knowledge_base: Dict[str, Any] = self.config.get("knowledge_base", {})
        self.known_facts: Dict[str, Set[str]] = self.config.get("known_facts", {})
        self.trusted_sources: Dict[str, SourceCredibility] = self.config.get("trusted_sources", {})
        self.strict_mode: bool = self.config.get("strict_mode", False)
        self.min_fact_confidence: float = self.config.get("min_fact_confidence", 0.6)
        self.check_temporal_consistency: bool = self.config.get("check_temporal_consistency", True)
        self.check_numerical_plausibility: bool = self.config.get("check_numerical_plausibility", True)
        self.max_unverified_fact_ratio: float = self.config.get("max_unverified_fact_ratio", 0.4)
        self.source_credibility_threshold: float = self.config.get("source_credibility_threshold", 0.4)
        self.common_knowledge_domains: Set[str] = set(
            self.config.get("common_knowledge_domains", [
                "geography", "history", "science", "mathematics",
                "astronomy", "biology", "chemistry", "physics",
            ])
        )
        self.logger.info("FactValidator initialized with strict_mode=%s", self.strict_mode)

    def validate(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate facts in content and return assessment."""
        self.logger.debug("Validating facts for content length: %d", len(content))
        facts = self.extract_facts(content)
        issues: List[FactIssue] = []
        for fact in facts:
            self._cross_reference_fact(fact)
            fact_issues = self._validate_single_fact(fact)
            issues.extend(fact_issues)
        temporal_issues = self._check_temporal_facts(facts) if self.check_temporal_consistency else []
        issues.extend(temporal_issues)
        numerical_issues = self._check_numerical_facts(facts) if self.check_numerical_plausibility else []
        issues.extend(numerical_issues)
        credibility_issues = self._assess_source_credibility(facts, context)
        issues.extend(credibility_issues)
        verified = sum(1 for f in facts if f.is_verified)
        unverified = len(facts) - verified
        overall_score = 1.0 - (unverified / max(1, len(facts))) * 0.5
        error_count = sum(1 for i in issues if i.severity == "error")
        overall_score -= error_count * 0.1
        overall_score = round(max(0.0, min(1.0, overall_score)), 4)
        result = {
            "valid": error_count == 0 and unverified / max(1, len(facts)) <= self.max_unverified_fact_ratio,
            "overall_score": overall_score,
            "facts": [
                {
                    "text": f.text,
                    "category": f.category,
                    "confidence": f.confidence,
                    "is_verified": f.is_verified,
                    "verification_source": f.verification_source,
                    "entities": f.entities,
                    "numerical_values": f.numerical_values,
                    "dates": f.dates,
                }
                for f in facts
            ],
            "issues": [
                {
                    "type": i.issue_type,
                    "fact": i.fact_text,
                    "description": i.description,
                    "severity": i.severity,
                    "confidence": i.confidence,
                    "suggestion": i.suggestion,
                }
                for i in issues
            ],
            "statistics": {
                "total_facts": len(facts),
                "verified_facts": verified,
                "unverified_facts": unverified,
                "verification_rate": round(verified / max(1, len(facts)), 4),
                "fact_density": round(len(facts) / max(1, len(content.split())), 4),
                "error_count": error_count,
                "warning_count": sum(1 for i in issues if i.severity == "warning"),
                "info_count": sum(1 for i in issues if i.severity == "info"),
                "category_breakdown": self._category_breakdown(facts),
            },
            "recommendations": self._generate_recommendations(issues, unverified, len(facts)),
        }
        self.logger.info(
            "Fact validation completed: valid=%s, score=%s, facts=%d, issues=%d",
            result["valid"], overall_score, len(facts), len(issues),
        )
        return result

    def extract_facts(self, content: str) -> List[Fact]:
        """Extract factual claims from content."""
        facts: List[Fact] = []
        seen_spans: Set[Tuple[int, int]] = set()
        sentences = re.split(r"(?<=[.!?])\s+", content)
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped or len(stripped) < 15:
                continue
            categories = self._categorize_sentence(stripped)
            if not categories:
                continue
            entities = ENTITY_PATTERN.findall(stripped)
            numerical_values = self._extract_numerical_values(stripped)
            dates = DATE_PATTERN.findall(stripped)
            start_pos = content.find(stripped)
            end_pos = start_pos + len(stripped) if start_pos >= 0 else 0
            for category in categories:
                fact = Fact(
                    text=stripped[:200],
                    category=category,
                    entities=entities,
                    numerical_values=numerical_values,
                    dates=dates,
                    start_pos=start_pos,
                    end_pos=end_pos,
                )
                fact_span = (fact.start_pos, fact.end_pos)
                if fact_span not in seen_spans:
                    seen_spans.add(fact_span)
                    facts.append(fact)
        return facts

    def _categorize_sentence(self, sentence: str) -> List[str]:
        """Categorize a sentence based on its factual content."""
        categories: List[str] = []
        sentence_lower = sentence.lower()
        numerical_patterns = [
            r"\d+%", r"\d+\s*percent", r"\d+\.\d+", r"\d+[-/]\d+",
            r"thousand", r"million", r"billion", r"trillion",
        ]
        for pat in numerical_patterns:
            if re.search(pat, sentence_lower):
                categories.append("numerical")
                break
        if ENTITY_PATTERN.search(sentence):
            categories.append("entity_claim")
        if DATE_PATTERN.search(sentence) or YEAR_PATTERN.search(sentence):
            categories.append("temporal")
        historical_indicators = [
            r"\bcentur", r"\bdecade", r"\bera\b", r"\bperiod\b",
            r"\bhistory\b", r"\boriginally\b", r"\btraditionally\b",
        ]
        for ind in historical_indicators:
            if re.search(ind, sentence_lower):
                categories.append("historical")
                break
        scientific_indicators = [
            r"\bstudy\b", r"\bresearch\b", r"\bscience\b", r"\bexperiment\b",
            r"\bhypothesis\b", r"\btheory\b", r"\blaw\b", r"\bformula\b",
            r"\bdiscover\b", r"\bevolution\b", r"\bgenetic\b",
        ]
        for ind in scientific_indicators:
            if re.search(ind, sentence_lower):
                categories.append("scientific")
                break
        geographical_indicators = [
            r"\bcountry\b", r"\bnation\b", r"\bcapital\b", r"\briver\b",
            r"\bmountain\b", r"\bocean\b", r"\bcontinent\b", r"\bregion\b",
            r"\bpopulation\b", r"\blocated\b", r"\bborder\b",
        ]
        for ind in geographical_indicators:
            if re.search(ind, sentence_lower):
                categories.append("geographical")
                break
        if "cited" in sentence_lower or "according to" in sentence_lower:
            categories.append("cited")
        if not categories:
            categories.append("general")
        return categories

    def _extract_numerical_values(self, text: str) -> List[float]:
        """Extract numerical values from text."""
        values: List[float] = []
        for match in NUMERICAL_PATTERN.finditer(text):
            num_str = match.group().replace(",", "").replace("%", "").strip().lower()
            if num_str in ("thousand", "million", "billion", "trillion", ""):
                continue
            try:
                values.append(float(num_str))
            except ValueError:
                continue
        return values

    def _cross_reference_fact(self, fact: Fact) -> None:
        """Cross-reference a fact with the knowledge base."""
        fact_lower = fact.text.lower()
        for domain, known_set in self.known_facts.items():
            for known in known_set:
                if known.lower() in fact_lower:
                    fact.is_verified = True
                    fact.verification_source = f"knowledge_base:{domain}"
                    fact.confidence = 0.9
                    return
        if self.knowledge_base:
            kb = self.knowledge_base
            for entity in fact.entities:
                entity_lower = entity.lower()
                if entity_lower in kb:
                    kb_entry = kb[entity_lower]
                    if isinstance(kb_entry, dict):
                        for key, value in kb_entry.items():
                            if str(value).lower() in fact_lower:
                                fact.is_verified = True
                                fact.verification_source = f"knowledge_base:{entity}"
                                fact.confidence = 0.85
                                return
        known_true_domains = {
            "water": ["h2o", "freezes", "boils", "liquid", "ocean", "sea"],
            "earth": ["planet", "orbit", "sphere", "globe", "rotation"],
            "sun": ["star", "solar", "light", "heat", "fusion"],
            "human": ["brain", "heart", "lungs", "cells", "dna"],
        }
        for domain, indicators in known_true_domains.items():
            if any(ind in fact_lower for ind in indicators):
                fact.confidence = max(fact.confidence, 0.7)
        for entity in fact.entities:
            if entity.lower() in KNOWN_TRUE_FACTS:
                for known in KNOWN_TRUE_FACTS[entity.lower()]:
                    if known in fact_lower:
                        fact.is_verified = True
                        fact.verification_source = f"common_knowledge:{entity}"
                        fact.confidence = 0.95
                        return

    def _validate_single_fact(self, fact: Fact) -> List[FactIssue]:
        """Validate a single fact for potential issues."""
        issues: List[FactIssue] = []
        if not fact.is_verified and fact.category not in ("general", "cited"):
            issues.append(FactIssue(
                issue_type="unverified_claim",
                fact_text=fact.text[:100],
                description=f"Unverified claim in category '{fact.category}'",
                severity="warning" if not self.strict_mode else "error",
                confidence=0.6,
                suggestion="Cross-reference this claim with reliable sources.",
            ))
        if fact.category == "scientific" and not fact.is_verified:
            issues.append(FactIssue(
                issue_type="unsupported_scientific_claim",
                fact_text=fact.text[:100],
                description="Scientific claim without supporting evidence or citation",
                severity="warning",
                confidence=0.7,
                suggestion="Provide citations to peer-reviewed research for scientific claims.",
            ))
        if fact.category == "historical" and not fact.is_verified and fact.confidence < 0.5:
            issues.append(FactIssue(
                issue_type="unverified_historical_claim",
                fact_text=fact.text[:100],
                description="Historical claim without verification",
                severity="warning",
                confidence=0.65,
                suggestion="Verify historical claims against authoritative sources.",
            ))
        if fact.category == "numerical" and fact.numerical_values:
            for val in fact.numerical_values:
                if self._is_implausible_value(val, fact.category):
                    issues.append(FactIssue(
                        issue_type="implausible_value",
                        fact_text=fact.text[:100],
                        description=f"Numerical value {val} appears implausible",
                        severity="error",
                        confidence=0.8,
                        suggestion=f"Verify the value {val} against reliable data sources.",
                    ))
        return issues

    def _is_implausible_value(self, value: float, category: str) -> bool:
        """Check if a numerical value is implausible for its category."""
        if value < 0:
            return False
        if category in ("geographical",):
            if value > 1_000_000_000_000:
                return True
            if 0 < value < 1 and value != 0.0:
                return False
        if category in ("temporal", "historical"):
            if value > datetime.now().year + 10:
                return True
            if 0 < value < 1000:
                if value != int(value):
                    return False
        if category == "numerical":
            if value > 1_000_000_000_000_000:
                return True
            if 0 < value < 0.0000001:
                return True
            return False
        return False

    def _check_temporal_facts(self, facts: List[Fact]) -> List[FactIssue]:
        """Check temporal consistency of facts."""
        issues: List[FactIssue] = []
        current_year = datetime.now().year
        for fact in facts:
            dates = DATE_PATTERN.findall(fact.text)
            years = YEAR_PATTERN.findall(fact.text)
            all_dates = dates + list(years)
            for date_str in all_dates:
                year = self._extract_year_from_date(date_str)
                if year is not None:
                    if year < 1800 and "century" not in fact.text.lower() and "bc" not in fact.text.lower():
                        issues.append(FactIssue(
                            issue_type="implausible_historical_date",
                            fact_text=fact.text[:100],
                            description=f"Date {date_str} seems unusually early for modern context",
                            severity="warning",
                            confidence=0.5,
                        ))
                    if year > current_year + 5:
                        issues.append(FactIssue(
                            issue_type="future_date",
                            fact_text=fact.text[:100],
                            description=f"Date {date_str} is in the future",
                            severity="error" if year > current_year + 10 else "warning",
                            confidence=min(0.9, 0.5 + (year - current_year) * 0.02),
                            suggestion=f"Verify the date {date_str} is correct.",
                        ))
        temporal_facts = [f for f in facts if f.category == "temporal"]
        if len(temporal_facts) >= 3:
            years_in_facts = []
            for tf in temporal_facts:
                years = YEAR_PATTERN.findall(tf.text)
                for y in years:
                    try:
                        years_in_facts.append(int(y))
                    except ValueError:
                        continue
            if len(years_in_facts) >= 3:
                years_in_facts.sort()
                if years_in_facts[-1] - years_in_facts[0] > 500:
                    issues.append(FactIssue(
                        issue_type="wide_temporal_range",
                        fact_text="",
                        description=f"Content spans {years_in_facts[-1] - years_in_facts[0]} years "
                                    f"({years_in_facts[0]}-{years_in_facts[-1]})",
                        severity="info",
                        confidence=0.4,
                    ))
                chronological = all(
                    years_in_facts[i] <= years_in_facts[i + 1]
                    for i in range(len(years_in_facts) - 1)
                )
                if not chronological:
                    issues.append(FactIssue(
                        issue_type="chronological_inconsistency",
                        fact_text="",
                        description="Dates appear in non-chronological order",
                        severity="warning",
                        confidence=0.6,
                        suggestion="Ensure temporal facts are presented in logical chronological order.",
                    ))
        return issues

    def _extract_year_from_date(self, date_str: str) -> Optional[int]:
        """Extract year from various date formats."""
        year_match = re.search(r"\b(19\d{2}|20[0-2]\d|2030)\b", date_str)
        if year_match:
            return int(year_match.group(1))
        return None

    def _check_numerical_facts(self, facts: List[Fact]) -> List[FactIssue]:
        """Check numerical fact plausibility and consistency."""
        issues: List[FactIssue] = []
        all_values: List[Tuple[float, str]] = []
        for fact in facts:
            for val in fact.numerical_values:
                all_values.append((val, fact.text[:60]))
        if len(all_values) < 3:
            return issues
        values_only = [v[0] for v in all_values]
        values_only.sort()
        q1 = values_only[len(values_only) // 4]
        q3 = values_only[3 * len(values_only) // 4]
        iqr = q3 - q1
        lower = q1 - 2.0 * iqr
        upper = q3 + 2.0 * iqr
        for val, text in all_values:
            if val != 0 and (val < lower or val > upper):
                issues.append(FactIssue(
                    issue_type="statistical_outlier",
                    fact_text=text,
                    description=f"Value {val} is a statistical outlier (IQR range: [{lower:.1f}, {upper:.1f}])",
                    severity="warning",
                    confidence=0.6,
                    suggestion=f"Verify the value {val} is accurate and not a data entry error.",
                ))
        for i in range(len(facts)):
            for j in range(i + 1, len(facts)):
                f1 = facts[i]
                f2 = facts[j]
                if not f1.numerical_values or not f2.numerical_values:
                    continue
                for v1 in f1.numerical_values:
                    for v2 in f2.numerical_values:
                        if v1 == v2:
                            continue
                        shared_entities = set(e.lower() for e in f1.entities) & set(e.lower() for e in f2.entities)
                        if shared_entities and abs(v1 - v2) / max(abs(v1), abs(v2), 1) > 0.5:
                            issues.append(FactIssue(
                                issue_type="contradictory_numbers",
                                fact_text=f1.text[:100],
                                description=f"Contradictory values ({v1} vs {v2}) for entity '{next(iter(shared_entities))}'",
                                severity="error",
                                confidence=0.75,
                                suggestion="Resolve the numerical contradiction between these statements.",
                            ))
        return issues

    def _assess_source_credibility(self, facts: List[Fact], context: Optional[Dict[str, Any]]) -> List[FactIssue]:
        """Assess credibility of cited sources."""
        issues: List[FactIssue] = []
        citations = re.findall(r"\([^)]*\d{4}[^)]*\)|\[[^\]]+\]", " ".join(f.text for f in facts))
        for citation_text in citations:
            source_match = re.search(r"according\s+to\s+([^,]+)", citation_text, re.IGNORECASE)
            if source_match:
                source_name = source_match.group(1).strip().lower()
                credibility = self._lookup_source_credibility(source_name)
                if credibility < self.source_credibility_threshold:
                    issues.append(FactIssue(
                        issue_type="low_credibility_source",
                        fact_text=citation_text[:80],
                        description=f"Source '{source_name}' has low credibility score ({credibility:.2f})",
                        severity="warning",
                        confidence=0.6,
                        suggestion=f"Consider using more authoritative sources instead of '{source_name}'.",
                    ))
        if context and "trusted_domains" in context:
            for fact in facts:
                for entity in fact.entities:
                    entity_lower = entity.lower()
                    for domain in context["trusted_domains"]:
                        if domain.lower() in entity_lower:
                            fact.is_verified = True
                            fact.verification_source = f"trusted_domain:{domain}"
                            fact.confidence = max(fact.confidence, 0.8)
        return issues

    def _lookup_source_credibility(self, source_name: str) -> float:
        """Look up or compute source credibility."""
        if source_name in self.trusted_sources:
            return self.trusted_sources[source_name].credibility_score
        academic_indicators = ["journal", "review", "university", "institute", "research"]
        government_indicators = ["gov", "government", "official", "agency", "department"]
        news_indicators = ["news", "times", "post", "daily", "press", "herald"]
        source_lower = source_name.lower()
        score = 0.5
        if any(ind in source_lower for ind in academic_indicators):
            score = 0.8
        if any(ind in source_lower for ind in government_indicators):
            score = 0.75
        if any(ind in source_lower for ind in news_indicators):
            score = 0.6
        red_flags = ["blog", "wiki", "forum", ".com", ".net"]
        if any(flag in source_lower for flag in red_flags):
            score = max(0.3, score - 0.2)
        return score

    def _category_breakdown(self, facts: List[Fact]) -> Dict[str, int]:
        """Compute category breakdown of facts."""
        breakdown: Dict[str, int] = {}
        for fact in facts:
            breakdown[fact.category] = breakdown.get(fact.category, 0) + 1
        return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))

    def _generate_recommendations(self, issues: List[FactIssue], unverified: int, total: int) -> List[str]:
        """Generate recommendations based on fact validation results."""
        recommendations: List[str] = []
        recommendations_map: Dict[str, str] = {
            "unverified_claim": "Cross-reference unverified claims with authoritative sources.",
            "unsupported_scientific_claim": "Provide citations to peer-reviewed research.",
            "unverified_historical_claim": "Verify historical claims against authoritative sources.",
            "implausible_value": "Review numerical values for accuracy and plausibility.",
            "implausible_historical_date": "Verify historical dates against reliable timelines.",
            "future_date": "Check future dates for accuracy.",
            "wide_temporal_range": "Ensure temporal consistency across the content.",
            "chronological_inconsistency": "Present dates in logical chronological order.",
            "statistical_outlier": "Verify statistical values against source data.",
            "contradictory_numbers": "Resolve contradictions between numerical claims.",
            "low_credibility_source": "Use authoritative sources for factual claims.",
        }
        seen_types: Set[str] = set()
        for issue in issues:
            if issue.issue_type not in seen_types:
                seen_types.add(issue.issue_type)
                rec = recommendations_map.get(issue.issue_type)
                if rec and rec not in recommendations:
                    recommendations.append(rec)
        if unverified > total * self.max_unverified_fact_ratio:
            recommendations.append("Increase verification rate by adding citations and references.")
        if not recommendations:
            recommendations.append("Factual claims appear well-supported and verified.")
        return recommendations

    def verify_single_fact(self, fact_statement: str) -> Dict[str, Any]:
        """Verify a single fact statement against the knowledge base."""
        entities = ENTITY_PATTERN.findall(fact_statement)
        numbers = self._extract_numerical_values(fact_statement)
        fact = Fact(
            text=fact_statement,
            category="general",
            entities=entities,
            numerical_values=numbers,
            dates=DATE_PATTERN.findall(fact_statement),
        )
        self._cross_reference_fact(fact)
        issues = self._validate_single_fact(fact)
        return {
            "text": fact_statement,
            "is_verified": fact.is_verified,
            "confidence": fact.confidence,
            "verification_source": fact.verification_source,
            "issues": [i.issue_type for i in issues],
            "category": fact.category,
        }

    def set_knowledge_base(self, kb: Dict[str, Any]) -> None:
        """Set the knowledge base for fact checking."""
        self.knowledge_base = kb

    def add_known_fact(self, domain: str, fact: str) -> None:
        """Add a known fact to the knowledge base."""
        if domain not in self.known_facts:
            self.known_facts[domain] = set()
        self.known_facts[domain].add(fact)

    def add_trusted_source(self, source_name: str, credibility: SourceCredibility) -> None:
        """Add a trusted source for fact verification."""
        self.trusted_sources[source_name.lower()] = credibility

    def get_fact_density(self, content: str) -> float:
        """Calculate fact density (facts per word)."""
        facts = self.extract_facts(content)
        words = content.split()
        if not words:
            return 0.0
        return round(len(facts) / len(words), 4)

    def get_verification_rate(self, facts: List[Fact]) -> float:
        """Get the verification rate of a list of facts."""
        if not facts:
            return 1.0
        verified = sum(1 for f in facts if f.is_verified)
        return round(verified / len(facts), 4)

    def categorize_facts(self, facts: List[Fact]) -> Dict[str, List[Fact]]:
        """Group facts by category."""
        categories: Dict[str, List[Fact]] = {}
        for fact in facts:
            if fact.category not in categories:
                categories[fact.category] = []
            categories[fact.category].append(fact)
        return categories

    def compare_facts_across_documents(self, docs: List[str]) -> List[Dict[str, Any]]:
        """Compare facts across multiple documents for consistency."""
        all_facts: List[Dict[str, Any]] = []
        for i, doc in enumerate(docs):
            facts = self.extract_facts(doc)
            for fact in facts:
                all_facts.append({
                    "doc_index": i,
                    "fact": fact.text,
                    "entities": fact.entities,
                    "numerical_values": fact.numerical_values,
                    "category": fact.category,
                })
        conflicts: List[Dict[str, Any]] = []
        for i in range(len(all_facts)):
            for j in range(i + 1, len(all_facts)):
                f1 = all_facts[i]
                f2 = all_facts[j]
                shared_entities = set(f1["entities"]) & set(f2["entities"])
                if shared_entities and f1["doc_index"] != f2["doc_index"]:
                    n1 = set(f1["numerical_values"])
                    n2 = set(f2["numerical_values"])
                    if n1 and n2 and n1 != n2:
                        conflicts.append({
                            "entity": list(shared_entities)[0],
                            "doc_1": f1["doc_index"],
                            "value_1": list(n1),
                            "doc_2": f2["doc_index"],
                            "value_2": list(n2),
                        })
        return conflicts

    def find_unsupported_claims(self, content: str, citations: List[str]) -> List[str]:
        """Find factual claims that lack supporting citations."""
        unsupported: List[str] = []
        facts = self.extract_facts(content)
        citation_text = " ".join(citations)
        citation_lower = citation_text.lower()
        for fact in facts:
            if fact.category in ("cited", "general"):
                continue
            fact_lower = fact.text.lower()
            fact_keywords = set(fact_lower.split()) - {"the", "a", "an", "is", "was", "are", "were", "in", "on", "at", "to", "for", "of", "and", "or", "by"}
            citation_keywords = set(citation_lower.split())
            overlap = len(fact_keywords & citation_keywords) / max(1, len(fact_keywords))
            if overlap < 0.2 and fact.category in ("scientific", "historical"):
                unsupported.append(fact.text[:120])
        return unsupported[:20]
