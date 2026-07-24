"""Age verification and content appropriateness."""
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AgeGroup(Enum):
    """Age group classifications."""
    CHILD = 'child'
    TEEN = 'teen'
    ADULT = 'adult'
    ALL_AGES = 'all'
    PRESCHOOL = 'preschool'
    YOUNG_CHILD = 'young_child'
    OLDER_CHILD = 'older_child'
    YOUNG_ADULT = 'young_adult'
    SENIOR = 'senior'


@dataclass
class ContentRating:
    """Content rating result."""
    rating: str
    age_group: str
    warnings: List[str]
    is_appropriate: bool
    matched_patterns: List[str] = field(default_factory=list)
    confidence_score: float = 1.0
    categories_flagged: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class AgeVerificationConfig:
    """Configuration for age verification."""
    enable_regex_matching: bool = True
    enable_context_awareness: bool = True
    enable_batch_verification: bool = True
    enable_statistics: bool = True
    min_confidence_threshold: float = 0.6
    max_warnings_before_block: int = 10
    educational_exemption_enabled: bool = True
    scientific_exemption_enabled: bool = True
    override_keywords: List[str] = field(default_factory=list)
    custom_categories: Dict[str, List[str]] = field(default_factory=dict)
    log_all_checks: bool = False
    cache_results: bool = True
    cache_ttl_seconds: int = 300


class AgeVerifier:
    """Verify content age appropriateness."""

    def __init__(self, config: Optional[AgeVerificationConfig] = None):
        self.config = config or AgeVerificationConfig()
        self.age_restricted_keywords = {
            AgeGroup.PRESCHOOL: [
                'violence', 'weapons', 'drugs', 'alcohol', 'gambling', 'death',
                'killing', 'horror', 'scary', 'monster', 'blood', 'injury',
                'weapon', 'gun', 'knife', 'explosion', 'poison', 'tobacco',
                'smoking', 'cigarette', 'beer', 'wine', 'liquor', 'sex',
                'nudity', 'profanity', 'swear', 'curse', 'drug abuse',
                'addiction', 'overdose', 'suicide', 'self_harm', 'cutting',
            ],
            AgeGroup.CHILD: [
                'violence', 'weapons', 'drugs', 'alcohol', 'gambling',
                'explicit', 'nudity', 'sex', 'profanity', 'gore', 'torture',
                'abuse', 'neglect', 'kidnapping', 'hostage', 'terrorism',
                'bomb', 'massacre', 'slaughter', 'genocide', 'execution',
                'human trafficking', 'prostitution', 'pornography', 'obscene',
                'predator', 'grooming', 'cyberbullying', 'harassment',
                'eating disorder', 'anorexia', 'bulimia', 'self harm',
            ],
            AgeGroup.YOUNG_CHILD: [
                'violence', 'weapons', 'drugs', 'alcohol', 'gambling',
                'explicit', 'nudity', 'sex', 'profanity', 'gore', 'torture',
                'abuse', 'neglect', 'kidnapping', 'terrorism', 'bomb',
                'pornography', 'obscene', 'predator', 'grooming',
                'cyberbullying', 'harassment', 'eating disorder',
                'self harm', 'suicide', 'depression', 'self_harm',
            ],
            AgeGroup.OLDER_CHILD: [
                'explicit', 'nudity', 'sex', 'gore', 'torture',
                'pornography', 'obscene', 'predator', 'grooming',
                'human trafficking', 'prostitution', 'hard drugs',
                'heroin', 'cocaine', 'meth', 'overdose', 'suicide',
                'self harm', 'cutting', 'eating disorder',
            ],
            AgeGroup.TEEN: [
                'explicit', 'gambling', 'substance abuse', 'hard drugs',
                'heroin', 'cocaine', 'meth', 'overdose', 'suicide',
                'self harm', 'cutting', 'pornography', 'obscene',
                'human trafficking', 'prostitution',
            ],
            AgeGroup.YOUNG_ADULT: [
                'explicit adult content', 'extreme gore', 'shock content',
                'obscene material', 'illegal activities instruction',
            ],
            AgeGroup.ADULT: [
                'explicit adult content', 'extreme gore', 'shock content',
                'obscene material', 'illegal activities instruction',
            ],
            AgeGroup.SENIOR: [
                'explicit adult content', 'extreme gore', 'shock content',
                'obscene material', 'illegal activities instruction',
            ],
            AgeGroup.ALL_AGES: [],
        }

        self.content_indicators = {
            'mild': ['cartoon', 'educational', 'family', 'preschool', 'children',
                     'nursery', 'kindergarten', 'storytime', 'lullaby', 'bedtime'],
            'moderate': ['action', 'fantasy', 'adventure', 'mystery', 'comedy',
                         'drama', 'romance', 'thriller', 'sci-fi', 'superhero'],
            'mature': ['violence', 'complex themes', 'realistic', 'psychological',
                       'dark', 'gritty', 'controversial', 'political', 'war',
                       'crime', 'noir', 'surreal', 'philosophical'],
        }

        self.regex_patterns = {
            'phone_number': re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
            'email_address': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'credit_card': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
            'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            'ip_address': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            'url': re.compile(r'https?://[^\s]+'),
            'profanity': re.compile(r'\b(fuck|shit|damn|bitch|ass|crap|dick|bastard)\b', re.IGNORECASE),
            'violence_descriptive': re.compile(r'\b(kill|murder|stab|shoot|beat|torture|slaughter)\w*\b', re.IGNORECASE),
            'drug_reference': re.compile(r'\b(cocaine|heroin|meth|marijuana|weed|lsd|ecstasy|opioid)\b', re.IGNORECASE),
            'sexual_content': re.compile(r'\b(sex|porn|nude|explicit|xxx|adult content)\b', re.IGNORECASE),
            'weapon_reference': re.compile(r'\b(gun|rifle|pistol|shotgun|bomb|explosive|knife|sword)\b', re.IGNORECASE),
            'self_harm': re.compile(r'\b(suicide|self.?harm|cutting|kill myself|end my life)\b', re.IGNORECASE),
            'gambling': re.compile(r'\b(bet|gambl|casino|poker|slot machine|lottery)\b', re.IGNORECASE),
            'alcohol': re.compile(r'\b(beer|wine|liquor|vodka|whiskey|rum|gin|alcohol|drunk|intoxicated)\b', re.IGNORECASE),
            'tobacco': re.compile(r'\b(cigarette|cigar|tobacco|smoking|vape|nicotine)\b', re.IGNORECASE),
            'hate_speech': re.compile(r'\b(hate|racist|nazi|white supremac|kkk)\b', re.IGNORECASE),
            'bullying': re.compile(r'\b(bully|loser|stupid|idiot|dumb|worthless|loser)\b', re.IGNORECASE),
            'eating_disorder': re.compile(r'\b(anorexia|bulimia|eating disorder|binge purge|thinspo)\b', re.IGNORECASE),
        }

        self.educational_contexts = re.compile(
            r'\b(study|learn|lesson|classroom|textbook|curriculum|academic|'
            r'university|college|school|education|research|science|history lesson|'
            r'biology|chemistry|physics|sociology|psychology|literature|'
            r'documentary|educational|teaching|professor|lecture|course)\b',
            re.IGNORECASE
        )

        self.scientific_contexts = re.compile(
            r'\b(science|scientific|study|research|experiment|laboratory|'
            r'clinical|medical|pharmaceutical|biological|chemical|'
            r'physiological|anatomical|psychological|sociological|'
            r'peer.?review|journal|publication|thesis|dissertation)\b',
            re.IGNORECASE
        )

        self.statistics = {
            'total_checks': 0,
            'total_appropriate': 0,
            'total_inappropriate': 0,
            'by_rating': defaultdict(int),
            'by_age_group': defaultdict(int),
            'by_category': defaultdict(int),
            'exemptions_granted': 0,
            'exemptions_denied': 0,
            'average_confidence': 0.0,
            'total_confidence_sum': 0.0,
            'check_history': [],
        }
        self.cache: Dict[str, Tuple[ContentRating, float]] = {}
        logger.info('AgeVerifier initialized with config')

    def _check_cache(self, cache_key: str) -> Optional[ContentRating]:
        if not self.config.cache_results:
            return None
        entry = self.cache.get(cache_key)
        if entry is None:
            return None
        result, expiry = entry
        if time.time() > expiry:
            del self.cache[cache_key]
            return None
        return result

    def _set_cache(self, cache_key: str, result: ContentRating) -> None:
        if self.config.cache_results:
            self.cache[cache_key] = (result, time.time() + self.config.cache_ttl_seconds)

    def _update_statistics(self, rating: ContentRating, is_exempted: bool = False) -> None:
        self.statistics['total_checks'] += 1
        if rating.is_appropriate:
            self.statistics['total_appropriate'] += 1
        else:
            self.statistics['total_inappropriate'] += 1
        self.statistics['by_rating'][rating.rating] += 1
        self.statistics['by_age_group'][rating.age_group] += 1
        for category in rating.categories_flagged:
            self.statistics['by_category'][category] += len(rating.categories_flagged[category])
        if is_exempted:
            self.statistics['exemptions_granted'] += 1
        self.statistics['total_confidence_sum'] += rating.confidence_score
        self.statistics['average_confidence'] = (
            self.statistics['total_confidence_sum'] / self.statistics['total_checks']
            if self.statistics['total_checks'] > 0 else 0.0
        )
        if len(self.statistics['check_history']) >= 1000:
            self.statistics['check_history'] = self.statistics['check_history'][-500:]
        self.statistics['check_history'].append({
            'timestamp': datetime.now().isoformat(),
            'rating': rating.rating,
            'age_group': rating.age_group,
            'appropriate': rating.is_appropriate,
            'warning_count': len(rating.warnings),
        })

    def verify_content_age_appropriateness(self, content: str, age_group: str) -> bool:
        content_lower = content.lower()
        restricted = self.age_restricted_keywords.get(AgeGroup(age_group), [])
        for keyword in restricted:
            if keyword in content_lower:
                logger.warning(f'Age-inappropriate content detected: {keyword}')
                return False
        for pattern_name, pattern in self.regex_patterns.items():
            if pattern.search(content) and pattern_name in ['profanity', 'violence_descriptive',
                                                            'drug_reference', 'sexual_content',
                                                            'weapon_reference', 'self_harm',
                                                            'gambling', 'alcohol', 'tobacco',
                                                            'hate_speech', 'bullying']:
                age_group_enum = AgeGroup(age_group)
                if age_group_enum in [AgeGroup.PRESCHOOL, AgeGroup.CHILD, AgeGroup.YOUNG_CHILD,
                                      AgeGroup.OLDER_CHILD, AgeGroup.TEEN]:
                    logger.warning(f'Regex pattern flagged for age group {age_group}: {pattern_name}')
                    return False
        return True

    def detect_age_restricted_content(self, content: str) -> List[str]:
        content_lower = content.lower()
        detected = []
        for age_group, keywords in self.age_restricted_keywords.items():
            for keyword in keywords:
                if keyword in content_lower:
                    detected.append(f'{age_group.value}: {keyword}')
        for pattern_name, pattern in self.regex_patterns.items():
            matches = pattern.findall(content)
            for match in matches:
                detected.append(f'regex:{pattern_name}: {match}')
        return detected

    def get_content_rating(self, content: str) -> str:
        content_lower = content.lower()
        adult_keywords = self.age_restricted_keywords[AgeGroup.ADULT]
        if any(kw in content_lower for kw in adult_keywords):
            return 'R'
        teen_keywords = self.age_restricted_keywords[AgeGroup.TEEN]
        if any(kw in content_lower for kw in teen_keywords):
            return 'PG-13'
        older_child_keywords = self.age_restricted_keywords[AgeGroup.OLDER_CHILD]
        if any(kw in content_lower for kw in older_child_keywords):
            return 'PG-13'
        child_keywords = self.age_restricted_keywords[AgeGroup.CHILD]
        if any(kw in content_lower for kw in child_keywords):
            return 'PG'
        preschool_keywords = self.age_restricted_keywords[AgeGroup.PRESCHOOL]
        if any(kw in content_lower for kw in preschool_keywords):
            return 'PG'
        if self.config.enable_regex_matching:
            if self.regex_patterns['sexual_content'].search(content):
                return 'R'
            if self.regex_patterns['violence_descriptive'].search(content):
                return 'PG-13'
            if self.regex_patterns['profanity'].search(content):
                return 'PG-13'
            if self.regex_patterns['self_harm'].search(content):
                return 'PG-13'
        return 'G'

    def _check_context_exemption(self, content: str) -> Tuple[bool, str]:
        if self.config.educational_exemption_enabled and self.educational_contexts.search(content):
            return True, 'educational'
        if self.config.scientific_exemption_enabled and self.scientific_contexts.search(content):
            return True, 'scientific'
        return False, ''

    def _categorize_flagged_content(self, content: str) -> Dict[str, List[str]]:
        categories: Dict[str, List[str]] = {}
        content_lower = content.lower()
        violence_words = ['kill', 'murder', 'stab', 'shoot', 'beat', 'torture',
                          'slaughter', 'violence', 'violent', 'blood', 'gore',
                          'weapon', 'gun', 'knife', 'bomb', 'explosion', 'war',
                          'attack', 'fight', 'punch', 'kick', 'strangle', 'wound',
                          'maim', 'cripple', 'assault', 'battle', 'combat']
        detected_violence = [w for w in violence_words if w in content_lower]
        if detected_violence:
            categories['violence'] = detected_violence

        drug_words = ['drug', 'cocaine', 'heroin', 'meth', 'marijuana', 'weed',
                      'lsd', 'ecstasy', 'opioid', 'fentanyl', 'addiction',
                      'overdose', 'substance', 'narcotic', 'pill', 'prescription']
        detected_drugs = [w for w in drug_words if w in content_lower]
        if detected_drugs:
            categories['substance_abuse'] = detected_drugs

        sexual_words = ['sex', 'sexual', 'porn', 'pornography', 'nude', 'nudity',
                        'explicit', 'xxx', 'adult content', 'erotic', 'obscene',
                        'intimate', 'seductive', 'provocative']
        detected_sexual = [w for w in sexual_words if w in content_lower]
        if detected_sexual:
            categories['sexual_content'] = detected_sexual

        hate_words = ['hate', 'racist', 'racism', 'nazi', 'white supremacist',
                      'kkk', 'bigot', 'discrimination', 'xenophobia',
                      'homophobic', 'transphobic', 'slur', 'intolerance']
        detected_hate = [w for w in hate_words if w in content_lower]
        if detected_hate:
            categories['hate_speech'] = detected_hate

        self_harm_words = ['suicide', 'self harm', 'self-harm', 'cutting',
                           'kill myself', 'end my life', 'depression',
                           'hopeless', 'worthless', 'self_harm', 'overdose',
                           'eating disorder', 'anorexia', 'bulimia']
        detected_self_harm = [w for w in self_harm_words if w in content_lower]
        if detected_self_harm:
            categories['self_harm'] = detected_self_harm

        bullying_words = ['bully', 'bullying', 'harass', 'harassment',
                          'loser', 'stupid', 'idiot', 'dumb', 'worthless',
                          'ugly', 'fat', 'loser', 'cyberbully']
        detected_bullying = [w for w in bullying_words if w in content_lower]
        if detected_bullying:
            categories['bullying'] = detected_bullying

        weapon_words = ['gun', 'rifle', 'pistol', 'shotgun', 'bomb',
                        'explosive', 'knife', 'sword', 'weapon', 'firearm',
                        'ammunition', 'missile', 'grenade', 'landmine']
        detected_weapons = [w for w in weapon_words if w in content_lower]
        if detected_weapons:
            categories['weapons'] = detected_weapons

        alcohol_words = ['beer', 'wine', 'liquor', 'vodka', 'whiskey',
                         'rum', 'gin', 'alcohol', 'drunk', 'intoxicated',
                         'cocktail', 'bar', 'pub', 'nightclub', 'binge']
        detected_alcohol = [w for w in alcohol_words if w in content_lower]
        if detected_alcohol:
            categories['alcohol'] = detected_alcohol

        tobacco_words = ['cigarette', 'cigar', 'tobacco', 'smoking',
                         'vape', 'nicotine', 'smoke', 'smoker', 'chewing tobacco']
        detected_tobacco = [w for w in tobacco_words if w in content_lower]
        if detected_tobacco:
            categories['tobacco'] = detected_tobacco

        gambling_words = ['bet', 'gamble', 'gambling', 'casino', 'poker',
                          'slot machine', 'lottery', 'blackjack', 'roulette',
                          'wagering', 'bookmaker', 'odds']
        detected_gambling = [w for w in gambling_words if w in content_lower]
        if detected_gambling:
            categories['gambling'] = detected_gambling

        return categories

    def comprehensive_check(self, content: str, target_age: str) -> ContentRating:
        cache_key = f"{hash(content)}:{target_age}"
        cached = self._check_cache(cache_key)
        if cached is not None:
            return cached

        rating = self.get_content_rating(content)
        matched_patterns = []
        categories_flagged = self._categorize_flagged_content(content)

        if self.config.enable_regex_matching:
            for pattern_name, pattern in self.regex_patterns.items():
                if pattern.search(content):
                    matched_patterns.append(pattern_name)

        warnings = self.detect_age_restricted_content(content)
        if len(warnings) > self.config.max_warnings_before_block:
            warnings.append("WARNING_COUNT_EXCEEDS_THRESHOLD")

        is_exempted = False
        if self.config.enable_context_awareness:
            exempted, context_type = self._check_context_exemption(content)
            if exempted:
                is_exempted = True
                warnings = [w for w in warnings if not w.startswith('regex:')]

        is_appropriate = self.verify_content_age_appropriateness(content, target_age)
        if is_exempted and not is_appropriate:
            is_appropriate = True
            warnings.append(f"EXEMPTED_VIA_CONTEXT")

        confidence = 1.0
        if len(warnings) > 0:
            confidence = max(0.1, 1.0 - (len(warnings) * 0.1))
        if is_exempted:
            confidence = min(confidence + 0.3, 1.0)

        age_group_enum = AgeGroup(target_age)
        if len(categories_flagged) >= 3 and age_group_enum in [
            AgeGroup.PRESCHOOL, AgeGroup.CHILD, AgeGroup.YOUNG_CHILD
        ]:
            confidence = max(0.0, confidence - 0.2)

        result = ContentRating(
            rating=rating,
            age_group=target_age,
            warnings=list(set(warnings)),
            is_appropriate=is_appropriate,
            matched_patterns=matched_patterns,
            confidence_score=confidence,
            categories_flagged=categories_flagged,
        )

        self._set_cache(cache_key, result)
        if self.config.enable_statistics:
            self._update_statistics(result, is_exempted)

        if self.config.log_all_checks:
            logger.info(f"Comprehensive check: age={target_age}, rating={rating}, "
                        f"appropriate={is_appropriate}, confidence={confidence:.2f}")

        return result

    def batch_verify(self, contents: List[Dict[str, str]]) -> List[ContentRating]:
        results = []
        for item in contents:
            content = item.get('content', '')
            age = item.get('age_group', 'all')
            result = self.comprehensive_check(content, age)
            results.append(result)
        logger.info(f"Batch verification completed: {len(results)} items")
        return results

    def get_content_rating_statistics(self) -> Dict[str, Any]:
        stats = {
            'total_checks': self.statistics['total_checks'],
            'total_appropriate': self.statistics['total_appropriate'],
            'total_inappropriate': self.statistics['total_inappropriate'],
            'appropriateness_rate': (
                self.statistics['total_appropriate'] / self.statistics['total_checks'] * 100
                if self.statistics['total_checks'] > 0 else 0.0
            ),
            'by_rating': dict(self.statistics['by_rating']),
            'by_age_group': dict(self.statistics['by_age_group']),
            'by_category': dict(self.statistics['by_category']),
            'exemptions_granted': self.statistics['exemptions_granted'],
            'exemptions_denied': self.statistics['exemptions_denied'],
            'average_confidence': round(self.statistics['average_confidence'], 4),
            'cache_size': len(self.cache),
            'recent_checks': self.statistics['check_history'][-20:],
            'generated_at': datetime.now().isoformat(),
        }
        return stats

    def get_rating_for_age_group(self, rating: str, target_age: str) -> bool:
        rating_map = {
            'G': [AgeGroup.ALL_AGES, AgeGroup.PRESCHOOL, AgeGroup.CHILD,
                  AgeGroup.YOUNG_CHILD, AgeGroup.OLDER_CHILD, AgeGroup.TEEN,
                  AgeGroup.YOUNG_ADULT, AgeGroup.ADULT, AgeGroup.SENIOR],
            'PG': [AgeGroup.OLDER_CHILD, AgeGroup.TEEN, AgeGroup.YOUNG_ADULT,
                   AgeGroup.ADULT, AgeGroup.SENIOR],
            'PG-13': [AgeGroup.TEEN, AgeGroup.YOUNG_ADULT, AgeGroup.ADULT, AgeGroup.SENIOR],
            'R': [AgeGroup.ADULT, AgeGroup.SENIOR],
        }
        allowed = rating_map.get(rating, [])
        return AgeGroup(target_age) in allowed

    def export_config(self) -> Dict[str, Any]:
        return {
            'enable_regex_matching': self.config.enable_regex_matching,
            'enable_context_awareness': self.config.enable_context_awareness,
            'enable_batch_verification': self.config.enable_batch_verification,
            'enable_statistics': self.config.enable_statistics,
            'min_confidence_threshold': self.config.min_confidence_threshold,
            'max_warnings_before_block': self.config.max_warnings_before_block,
            'educational_exemption_enabled': self.config.educational_exemption_enabled,
            'scientific_exemption_enabled': self.config.scientific_exemption_enabled,
            'log_all_checks': self.config.log_all_checks,
            'cache_results': self.config.cache_results,
            'cache_ttl_seconds': self.config.cache_ttl_seconds,
        }

    def clear_cache(self) -> int:
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"Cache cleared: {count} entries removed")
        return count

    def reset_statistics(self) -> None:
        self.statistics = {
            'total_checks': 0, 'total_appropriate': 0, 'total_inappropriate': 0,
            'by_rating': defaultdict(int), 'by_age_group': defaultdict(int),
            'by_category': defaultdict(int), 'exemptions_granted': 0,
            'exemptions_denied': 0, 'average_confidence': 0.0,
            'total_confidence_sum': 0.0, 'check_history': [],
        }
        logger.info("Statistics reset")

    def add_custom_keywords(self, age_group: str, keywords: List[str]) -> None:
        group = AgeGroup(age_group)
        if group in self.age_restricted_keywords:
            self.age_restricted_keywords[group].extend(keywords)
            logger.info(f"Added {len(keywords)} keywords to {age_group}")

    def add_custom_regex_pattern(self, name: str, pattern: str) -> None:
        self.regex_patterns[name] = re.compile(pattern)
        logger.info(f"Added regex pattern: {name}")

    def check_content_safe_for_preschool(self, content: str) -> ContentRating:
        return self.comprehensive_check(content, AgeGroup.PRESCHOOL.value)

    def check_content_safe_for_teens(self, content: str) -> ContentRating:
        return self.comprehensive_check(content, AgeGroup.TEEN.value)

    def check_content_safe_for_adults(self, content: str) -> ContentRating:
        return self.comprehensive_check(content, AgeGroup.ADULT.value)

    def get_content_categories(self, content: str) -> Dict[str, List[str]]:
        return self._categorize_flagged_content(content)

    def verify_content_safe(self, content: str) -> Tuple[bool, List[str]]:
        result = self.comprehensive_check(content, AgeGroup.CHILD.value)
        return result.is_appropriate, result.warnings

    def get_top_flagged_categories(self, limit: int = 5) -> List[Tuple[str, int]]:
        sorted_categories = sorted(
            self.statistics['by_category'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_categories[:limit]

    def get_rating_distribution(self) -> Dict[str, float]:
        total = self.statistics['total_checks']
        if total == 0:
            return {}
        return {
            rating: (count / total * 100)
            for rating, count in self.statistics['by_rating'].items()
        }

    def get_age_group_distribution(self) -> Dict[str, float]:
        total = self.statistics['total_checks']
        if total == 0:
            return {}
        return {
            group: (count / total * 100)
            for group, count in self.statistics['by_age_group'].items()
        }

    def generate_report(self, include_history: bool = False) -> Dict[str, Any]:
        report = {
            'statistics': self.get_content_rating_statistics(),
            'rating_distribution': self.get_rating_distribution(),
            'age_group_distribution': self.get_age_group_distribution(),
            'top_categories': self.get_top_flagged_categories(),
            'config': self.export_config(),
        }
        if include_history:
            report['recent_history'] = self.statistics['check_history'][-50:]
        return report

    def get_recommended_age_group(self, content: str) -> str:
        rating = self.get_content_rating(content)
        mapping = {
            'G': AgeGroup.ALL_AGES.value,
            'PG': AgeGroup.OLDER_CHILD.value,
            'PG-13': AgeGroup.TEEN.value,
            'R': AgeGroup.ADULT.value,
        }
        return mapping.get(rating, AgeGroup.ALL_AGES.value)

    def check_multiple_age_groups(self, content: str) -> Dict[str, bool]:
        results = {}
        for group in AgeGroup:
            if group == AgeGroup.ALL_AGES:
                continue
            result = self.verify_content_age_appropriateness(content, group.value)
            results[group.value] = result
        return results

    def find_inappropriate_keywords(self, content: str) -> Dict[str, List[str]]:
        content_lower = content.lower()
        found: Dict[str, List[str]] = {}
        for group, keywords in self.age_restricted_keywords.items():
            matched = [kw for kw in keywords if kw in content_lower]
            if matched:
                found[group.value] = matched
        return found

    def get_safe_content_score(self, content: str, target_age: str) -> float:
        result = self.comprehensive_check(content, target_age)
        score = result.confidence_score
        if not result.is_appropriate:
            score = score * 0.5
        if len(result.warnings) > 5:
            score = score * 0.7
        return round(max(0.0, min(1.0, score)), 4)

    def check_content_for_all_ages(self, content: str) -> ContentRating:
        return self.comprehensive_check(content, AgeGroup.ALL_AGES.value)