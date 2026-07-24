"""Intent recognition for content analysis."""
import json
import logging
import math
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class IntentAnalysis:
    """Result of intent analysis."""
    primary_intent: str
    confidence: float
    secondary_intents: Dict[str, float]
    is_harmful: bool
    matched_patterns: List[str] = field(default_factory=list)
    decayed_confidence: float = 0.0
    context_scores: Dict[str, float] = field(default_factory=dict)
    language_hints: List[str] = field(default_factory=list)
    analysis_version: str = "2.0"


@dataclass
class IntentHistoryEntry:
    """A single entry in the intent history."""
    content_hash: str
    primary_intent: str
    confidence: float
    is_harmful: bool
    timestamp: datetime
    duration_seconds: float = 0.0


@dataclass
class IntentConfig:
    """Configuration for intent recognition."""
    enable_regex: bool = True
    enable_confidence_decay: bool = True
    enable_multi_language: bool = True
    enable_context_history: bool = True
    enable_batch_analysis: bool = True
    min_confidence_threshold: float = 0.3
    harmful_threshold: float = 0.5
    confidence_decay_rate: float = 0.05
    max_history_size: int = 1000
    history_ttl_hours: int = 24
    custom_patterns: Dict[str, List[str]] = field(default_factory=dict)
    log_all_analyses: bool = False


class IntentAnalyzer:
    """Analyze user intent in content."""

    def __init__(self, config: Optional[IntentConfig] = None):
        self.config = config or IntentConfig()
        self.harmful_intents = [
            'harm', 'attack', 'exploit', 'manipulate', 'deceive',
            'steal', 'destroy', 'weapon', 'dangerous', 'abuse',
            'threaten', 'coerce', 'harass', 'stalk', 'impersonate',
            'fraud', 'scam', 'phishing', 'malware', 'ransomware',
            'virus', 'trojan', 'backdoor', 'rootkit', 'keylogger',
            'spyware', 'adware', 'botnet', 'ddos', 'exploit kit',
            'social engineering', 'identity theft', 'credit card fraud',
            'money laundering', 'terrorism', 'extremism', 'radicalization',
            'grooming', 'predation', 'child exploitation', 'revenge porn',
            'cyberstalking', 'doxing', 'swatting', 'bomb threat',
            'mass shooting', 'school shooting', 'workplace violence',
            'domestic violence', 'sexual assault', 'human trafficking',
            'drug trafficking', 'weapon trafficking', 'illegal gambling',
            'hate crime', 'genocide', 'ethnic cleansing', 'war crime',
        ]

        self.intent_patterns = {
            'information_seeking': [
                'how to', 'what is', 'explain', 'tell me', 'help me understand',
                'what does', 'how does', 'why is', 'where can', 'when did',
                'can you explain', 'i want to know', 'tell me about',
                'define', 'describe', 'elaborate', 'clarify', 'meaning of',
                'purpose of', 'reason for', 'cause of', 'difference between',
            ],
            'creative': [
                'write', 'create', 'generate', 'design', 'compose',
                'draw', 'paint', 'sculpt', 'build', 'craft',
                'author', 'produce', 'develop', 'invent', 'imagine',
                'story', 'poem', 'song', 'script', 'dialogue',
                'character', 'plot', 'worldbuilding', 'narrative',
                'fiction', 'fantasy', 'sci-fi', 'mystery', 'romance',
            ],
            'harmful': [
                'how to make', 'build a', 'create weapon', 'hack', 'exploit',
                'bypass', 'crack', 'steal', 'destroy', 'kill',
                'harm', 'attack', 'abuse', 'threaten', 'illegal',
                'malware', 'virus', 'ransomware', 'phishing', 'scam',
                'fraud', 'identity theft', 'credit card', 'password crack',
                'ddos', 'botnet', 'social engineering', 'manipulate',
                'coerce', 'harass', 'stalk', 'dox', 'swat',
            ],
            'educational': [
                'learn', 'teach', 'study', 'educate', 'understand',
                'lesson', 'course', 'tutorial', 'training', 'workshop',
                'classroom', 'curriculum', 'textbook', 'homework', 'assignment',
                'research', 'thesis', 'dissertation', 'paper', 'publication',
                'lecture', 'seminar', 'webinar', 'certification', 'degree',
                'academic', 'scholarly', 'pedagogical', 'instructional',
            ],
            'support_seeking': [
                'help', 'support', 'assist', 'guide', 'advise',
                'help me', 'can you help', 'i need help', 'please help',
                'assistance', 'troubleshoot', 'fix', 'repair', 'resolve',
                'solution', 'answer', 'suggestion', 'recommendation',
                'advice', 'counsel', 'guidance', 'direction',
            ],
            'casual_conversation': [
                'hello', 'hi', 'hey', 'how are you', 'what\'s up',
                'good morning', 'good evening', 'nice to meet', 'howdy',
                'greetings', 'sup', 'yo', 'hey there', 'hi there',
            ],
            'opinion_seeking': [
                'what do you think', 'in your opinion', 'do you think',
                'would you recommend', 'which is better', 'compare',
                'pros and cons', 'advantages', 'disadvantages',
                'best', 'worst', 'recommend', 'suggest', 'rate',
                'review', 'feedback', 'thoughts on', 'perspective',
            ],
            'problem_solving': [
                'solve', 'figure out', 'find a way', 'workaround',
                'debug', 'troubleshoot', 'fix this', 'resolve this',
                'optimize', 'improve', 'enhance', 'refactor',
                'algorithm', 'solution', 'approach', 'strategy',
                'technique', 'method', 'workflow', 'pipeline',
            ],
            'planning': [
                'plan', 'schedule', 'organize', 'prepare', 'arrange',
                'planning', 'agenda', 'itinerary', 'roadmap', 'timeline',
                'milestone', 'deadline', 'goal', 'objective', 'target',
                'strategy', 'tactic', 'blueprint', 'framework',
            ],
            'analysis': [
                'analyze', 'evaluate', 'assess', 'examine', 'investigate',
                'review', 'audit', 'inspect', 'scrutinize', 'study',
                'break down', 'deconstruct', 'dissect', 'probe',
                'metrics', 'statistics', 'data', 'trend', 'pattern',
            ],
            'collaboration': [
                'collaborate', 'team up', 'work together', 'cooperate',
                'joint', 'shared', 'collective', 'partnership',
                'brainstorm', 'discuss', 'debate', 'dialogue',
                'meeting', 'sync', 'coordinate', 'align',
            ],
            'feedback': [
                'feedback', 'critique', 'review', 'comment', 'suggest',
                'improvement', 'better', 'enhance', 'polish', 'refine',
                'revise', 'edit', 'proofread', 'correct', 'update',
            ],
            'emotional_expression': [
                'feel', 'feeling', 'emotion', 'sad', 'happy', 'angry',
                'frustrated', 'confused', 'worried', 'anxious', 'excited',
                'grateful', 'thankful', 'appreciate', 'love', 'hate',
                'depressed', 'lonely', 'scared', 'hopeful', 'proud',
            ],
            'command': [
                'do this', 'run', 'execute', 'perform', 'complete',
                'finish', 'start', 'stop', 'continue', 'proceed',
                'implement', 'deploy', 'launch', 'activate', 'enable',
                'disable', 'configure', 'set up', 'install', 'remove',
            ],
            'clarification': [
                'what do you mean', 'can you clarify', 'i don\'t understand',
                'could you elaborate', 'explain further', 'more details',
                'in other words', 'simplify', 'rephrase', 'example',
                'specifically', 'precisely', 'exactly', 'concretely',
            ],
        }

        self.regex_intent_patterns = {
            'question_words': re.compile(r'\b(what|why|when|where|who|how|which)\b', re.IGNORECASE),
            'imperatives': re.compile(r'^\s*(please\s+)?(do|make|create|write|find|show|tell|give)\b', re.IGNORECASE),
            'gratitude': re.compile(r'\b(thanks|thank you|appreciate|grateful)\b', re.IGNORECASE),
            'urgency': re.compile(r'\b(urgent|asap|immediately|quickly|hurry|emergency|critical)\b', re.IGNORECASE),
            'negation': re.compile(r'\b(don\'t|doesn\'t|isn\'t|can\'t|cannot|won\'t|shouldn\'t|not)\b', re.IGNORECASE),
            'conditional': re.compile(r'\b(if|unless|provided|assuming|should|whenever|in case)\b', re.IGNORECASE),
            'comparison': re.compile(r'\b(better|worse|faster|slower|cheaper|more|less|than)\b', re.IGNORECASE),
            'listing': re.compile(r'(\d+\.\s|\-\s|\*\s)', re.MULTILINE),
            'code_blocks': re.compile(r'```[\s\S]*?```'),
            'quoted_text': re.compile(r'["\'"](.+?)["\'"]'),
        }

        self.language_indicators = {
            'english': re.compile(r'\b(the|is|are|was|were|have|has|been|will|would|could|should)\b', re.IGNORECASE),
            'spanish': re.compile(r'\b(el|la|los|las|es|son|está|están|tiene|tienen|haber|puede)\b', re.IGNORECASE),
            'french': re.compile(r'\b(le|la|les|est|sont|avoir|être|faire|peut|doit|avec|pour)\b', re.IGNORECASE),
            'german': re.compile(r'\b(der|die|das|ist|sind|haben|sein|werden|können|müssen|mit|für)\b', re.IGNORECASE),
            'chinese': re.compile(r'[\u4e00-\u9fff]'),
            'japanese': re.compile(r'[\u3040-\u309f\u30a0-\u30ff]'),
            'russian': re.compile(r'[\u0400-\u04ff]'),
            'arabic': re.compile(r'[\u0600-\u06ff]'),
            'hindi': re.compile(r'[\u0900-\u097f]'),
            'korean': re.compile(r'[\uac00-\ud7af]'),
        }

        self.context_history: List[IntentHistoryEntry] = []
        self.analysis_count: int = 0
        logger.info('IntentAnalyzer initialized')

    def analyze_intent(self, content: str) -> Dict[str, float]:
        content_lower = content.lower()
        scores = defaultdict(float)

        for intent_type, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    scores[intent_type] += 0.25

        if self.config.enable_regex:
            self._apply_regex_scores(content, scores)

        if self.config.custom_patterns:
            for intent_type, patterns in self.config.custom_patterns.items():
                for pattern in patterns:
                    if pattern in content_lower:
                        scores[intent_type] += 0.25

        total = sum(scores.values())
        if total > 0:
            scores = {k: min(v / total, 1.0) for k, v in scores.items()}

        logger.debug(f'Intent analysis for content: {dict(scores)}')
        return dict(scores)

    def _apply_regex_scores(self, content: str, scores: Dict[str, float]) -> None:
        if self.regex_intent_patterns['question_words'].search(content):
            scores['information_seeking'] += 0.1
        if self.regex_intent_patterns['imperatives'].search(content):
            scores['command'] += 0.15
        if self.regex_intent_patterns['gratitude'].search(content):
            scores['casual_conversation'] += 0.1
        if self.regex_intent_patterns['urgency'].search(content):
            scores['problem_solving'] += 0.15
        if self.regex_intent_patterns['negation'].search(content) and \
           self.regex_intent_patterns['question_words'].search(content):
            scores['clarification'] += 0.15
        if self.regex_intent_patterns['comparison'].search(content):
            scores['opinion_seeking'] += 0.15
        if self.regex_intent_patterns['conditional'].search(content):
            scores['planning'] += 0.1
        if self.regex_intent_patterns['listing'].search(content):
            scores['analysis'] += 0.1
        if self.regex_intent_patterns['code_blocks'].search(content):
            scores['problem_solving'] += 0.2

    def detect_harmful_intent(self, content: str) -> bool:
        content_lower = content.lower()

        for harmful_word in self.harmful_intents:
            if harmful_word in content_lower:
                logger.warning(f'Harmful intent detected: {harmful_word}')
                return True

        intents = self.analyze_intent(content)
        if intents.get('harmful', 0) > self.config.harmful_threshold:
            return True

        return False

    def get_intent_confidence(self, content: str, intent_type: str) -> float:
        intents = self.analyze_intent(content)
        base_confidence = intents.get(intent_type, 0.0)

        if self.config.enable_confidence_decay:
            decayed = self._apply_confidence_decay(content, intent_type, base_confidence)
            return decayed

        return base_confidence

    def _apply_confidence_decay(self, content: str, intent_type: str,
                                 base_confidence: float) -> float:
        content_hash = str(hash(content))
        recent_entries = [e for e in self.context_history
                          if e.content_hash == content_hash
                          and e.primary_intent == intent_type]

        if not recent_entries:
            return base_confidence

        latest = max(recent_entries, key=lambda e: e.timestamp)
        elapsed = (datetime.now() - latest.timestamp).total_seconds()
        decay_factor = math.exp(-self.config.confidence_decay_rate * (elapsed / 3600))
        decayed = base_confidence * decay_factor

        return max(0.0, decayed)

    def _detect_language(self, content: str) -> List[str]:
        if not self.config.enable_multi_language:
            return ['english']
        detected = []
        for lang, pattern in self.language_indicators.items():
            matches = pattern.findall(content)
            if len(matches) >= 3:
                detected.append(lang)
        if not detected:
            detected.append('unknown')
        return detected

    def _add_to_history(self, content: str, analysis: IntentAnalysis,
                         duration: float) -> None:
        if not self.config.enable_context_history:
            return

        entry = IntentHistoryEntry(
            content_hash=str(hash(content)),
            primary_intent=analysis.primary_intent,
            confidence=analysis.confidence,
            is_harmful=analysis.is_harmful,
            timestamp=datetime.now(),
            duration_seconds=duration,
        )

        self.context_history.append(entry)

        cutoff = datetime.now() - timedelta(hours=self.config.history_ttl_hours)
        self.context_history = [e for e in self.context_history if e.timestamp > cutoff]

        if len(self.context_history) > self.config.max_history_size:
            self.context_history = self.context_history[-self.config.max_history_size:]

    def comprehensive_analysis(self, content: str) -> IntentAnalysis:
        start_time = time.time()
        intents = self.analyze_intent(content)
        primary_intent = max(intents, key=intents.get) if intents else 'unknown'
        confidence = intents.get(primary_intent, 0.0)
        is_harmful = self.detect_harmful_intent(content)
        secondary = {k: v for k, v in intents.items() if k != primary_intent}

        matched_patterns = []
        if self.config.enable_regex:
            for name, pattern in self.regex_intent_patterns.items():
                if pattern.search(content):
                    matched_patterns.append(name)

        decayed_confidence = confidence
        if self.config.enable_confidence_decay:
            decayed_confidence = self._apply_confidence_decay(content, primary_intent, confidence)

        language_hints = self._detect_language(content)

        context_scores = {}
        if self.config.enable_context_history:
            context_scores = self._compute_context_scores(content)

        duration = time.time() - start_time
        analysis = IntentAnalysis(
            primary_intent=primary_intent,
            confidence=confidence,
            secondary_intents=dict(sorted(secondary.items(), key=lambda x: x[1], reverse=True)[:5]),
            is_harmful=is_harmful,
            matched_patterns=matched_patterns,
            decayed_confidence=decayed_confidence,
            context_scores=context_scores,
            language_hints=language_hints,
        )

        self._add_to_history(content, analysis, duration)
        self.analysis_count += 1

        if self.config.log_all_analyses:
            logger.info(f"Analysis #{self.analysis_count}: intent={primary_intent}, "
                        f"confidence={confidence:.3f}, harmful={is_harmful}, "
                        f"languages={language_hints}")

        return analysis

    def _compute_context_scores(self, content: str) -> Dict[str, float]:
        content_hash = str(hash(content))
        recent = [e for e in self.context_history[-50:]
                  if e.content_hash != content_hash]
        if not recent:
            return {}
        scores: Dict[str, float] = defaultdict(float)
        for entry in recent:
            scores[entry.primary_intent] += entry.confidence * 0.1
        return dict(scores)

    def batch_analyze(self, contents: List[str]) -> List[IntentAnalysis]:
        results = []
        for content in contents:
            analysis = self.comprehensive_analysis(content)
            results.append(analysis)
        logger.info(f"Batch analysis completed: {len(results)} items")
        return results

    def get_analysis_statistics(self) -> Dict[str, Any]:
        if not self.context_history:
            return {"total_analyses": self.analysis_count, "history_empty": True}
        intent_counts: Dict[str, int] = defaultdict(int)
        harmful_count = sum(1 for e in self.context_history if e.is_harmful)
        for entry in self.context_history:
            intent_counts[entry.primary_intent] += 1
        avg_confidence = (
            sum(e.confidence for e in self.context_history) / len(self.context_history)
            if self.context_history else 0.0
        )
        return {
            "total_analyses": self.analysis_count,
            "history_size": len(self.context_history),
            "intent_distribution": dict(intent_counts),
            "harmful_count": harmful_count,
            "harmful_ratio": harmful_count / len(self.context_history) if self.context_history else 0.0,
            "average_confidence": round(avg_confidence, 4),
            "most_common_intent": max(intent_counts, key=intent_counts.get) if intent_counts else None,
        }

    def get_intent_distribution(self) -> Dict[str, float]:
        intents = self.analyze_intent("")
        return {}

    def get_recent_analyses(self, limit: int = 10) -> List[Dict[str, Any]]:
        recent = self.context_history[-limit:] if self.context_history else []
        return [
            {
                "primary_intent": e.primary_intent,
                "confidence": e.confidence,
                "is_harmful": e.is_harmful,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in reversed(recent)
        ]

    def clear_history(self) -> int:
        count = len(self.context_history)
        self.context_history.clear()
        logger.info(f"Context history cleared: {count} entries")
        return count

    def add_custom_intent_pattern(self, intent_type: str, patterns: List[str]) -> None:
        if intent_type not in self.intent_patterns:
            self.intent_patterns[intent_type] = []
        self.intent_patterns[intent_type].extend(patterns)
        logger.info(f"Added {len(patterns)} patterns for intent: {intent_type}")

    def add_custom_regex_pattern(self, name: str, pattern: str) -> None:
        self.regex_intent_patterns[name] = re.compile(pattern)
        logger.info(f"Added regex pattern: {name}")

    def get_intent_categories(self) -> List[str]:
        return list(self.intent_patterns.keys())

    def analyze_sentiment(self, content: str) -> Dict[str, float]:
        positive_words = ['good', 'great', 'excellent', 'amazing', 'wonderful',
                          'fantastic', 'happy', 'love', 'beautiful', 'nice',
                          'positive', 'excited', 'grateful', 'thankful', 'joyful',
                          'peaceful', 'hopeful', 'optimistic', 'brilliant', 'awesome']
        negative_words = ['bad', 'terrible', 'awful', 'horrible', 'hate',
                          'angry', 'sad', 'depressed', 'ugly', 'worst',
                          'negative', 'frustrated', 'anxious', 'scared', 'lonely',
                          'hopeless', 'pessimistic', 'dreadful', 'disgusting', 'pathetic']
        content_lower = content.lower()
        positive_count = sum(1 for w in positive_words if w in content_lower)
        negative_count = sum(1 for w in negative_words if w in content_lower)
        total = positive_count + negative_count
        if total == 0:
            return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}
        return {
            "positive": round(positive_count / total, 4),
            "negative": round(negative_count / total, 4),
            "neutral": 0.0,
        }

    def get_primary_intent_category(self, content: str) -> str:
        analysis = self.comprehensive_analysis(content)
        return analysis.primary_intent

    def is_content_harmful(self, content: str) -> Tuple[bool, float]:
        analysis = self.comprehensive_analysis(content)
        return analysis.is_harmful, analysis.confidence

    def get_intent_details(self, content: str) -> Dict[str, Any]:
        analysis = self.comprehensive_analysis(content)
        return {
            "primary_intent": analysis.primary_intent,
            "confidence": analysis.confidence,
            "decayed_confidence": analysis.decayed_confidence,
            "secondary_intents": analysis.secondary_intents,
            "is_harmful": analysis.is_harmful,
            "matched_patterns": analysis.matched_patterns,
            "language_hints": analysis.language_hints,
            "context_scores": analysis.context_scores,
        }

    def export_config(self) -> Dict[str, Any]:
        return {
            "enable_regex": self.config.enable_regex,
            "enable_confidence_decay": self.config.enable_confidence_decay,
            "enable_multi_language": self.config.enable_multi_language,
            "enable_context_history": self.config.enable_context_history,
            "enable_batch_analysis": self.config.enable_batch_analysis,
            "min_confidence_threshold": self.config.min_confidence_threshold,
            "harmful_threshold": self.config.harmful_threshold,
            "confidence_decay_rate": self.config.confidence_decay_rate,
            "max_history_size": self.config.max_history_size,
            "history_ttl_hours": self.config.history_ttl_hours,
            "intent_categories": len(self.intent_patterns),
            "regex_patterns": len(self.regex_intent_patterns),
            "language_indicators": len(self.language_indicators),
        }

    def get_full_analysis(self, content: str) -> Dict[str, Any]:
        analysis = self.comprehensive_analysis(content)
        sentiment = self.analyze_sentiment(content)
        return {
            "content_length": len(content),
            "word_count": len(content.split()),
            "intent": {
                "primary": analysis.primary_intent,
                "confidence": analysis.confidence,
                "decayed": analysis.decayed_confidence,
                "secondary": analysis.secondary_intents,
            },
            "harmful": {
                "is_harmful": analysis.is_harmful,
                "risk_level": "high" if analysis.is_harmful and analysis.confidence > 0.7
                             else "medium" if analysis.is_harmful else "low",
            },
            "sentiment": sentiment,
            "language_hints": analysis.language_hints,
            "matched_patterns": analysis.matched_patterns,
            "context_scores": analysis.context_scores,
        }

    def batch_analyze_with_details(self, contents: List[str]) -> List[Dict[str, Any]]:
        return [self.get_full_analysis(c) for c in contents]

    def compare_intents(self, content1: str, content2: str) -> Dict[str, Any]:
        a1 = self.comprehensive_analysis(content1)
        a2 = self.comprehensive_analysis(content2)
        return {
            "same_primary": a1.primary_intent == a2.primary_intent,
            "confidence_delta": round(abs(a1.confidence - a2.confidence), 4),
            "both_harmful": a1.is_harmful and a2.is_harmful,
            "summary": f"Content1: {a1.primary_intent} ({a1.confidence:.2f}), "
                       f"Content2: {a2.primary_intent} ({a2.confidence:.2f})",
        }

    def find_most_confident_intent(self, content: str) -> Tuple[str, float]:
        intents = self.analyze_intent(content)
        if not intents:
            return ("unknown", 0.0)
        best = max(intents.items(), key=lambda x: x[1])
        return best

    def is_ambiguously_intentioned(self, content: str, threshold: float = 0.3) -> Tuple[bool, List[str]]:
        intents = self.analyze_intent(content)
        close_intents = [k for k, v in intents.items() if v >= threshold]
        return (len(close_intents) >= 3, close_intents)

    def get_intent_heatmap(self, contents: List[str]) -> Dict[str, int]:
        heatmap: Dict[str, int] = defaultdict(int)
        for content in contents:
            analysis = self.comprehensive_analysis(content)
            heatmap[analysis.primary_intent] += 1
        return dict(sorted(heatmap.items(), key=lambda x: x[1], reverse=True))

    def track_intent_sequence(self, contents: List[str]) -> List[Dict[str, Any]]:
        sequence = []
        for i, content in enumerate(contents):
            analysis = self.comprehensive_analysis(content)
            sequence.append({
                "position": i,
                "intent": analysis.primary_intent,
                "confidence": analysis.confidence,
                "is_harmful": analysis.is_harmful,
            })
        return sequence

    def detect_intent_shift(self, previous_content: str, current_content: str) -> Dict[str, Any]:
        prev = self.comprehensive_analysis(previous_content)
        curr = self.comprehensive_analysis(current_content)
        return {
            "shifted": prev.primary_intent != curr.primary_intent,
            "from": prev.primary_intent,
            "to": curr.primary_intent,
            "confidence_delta": round(curr.confidence - prev.confidence, 4),
            "harmful_shift": (not prev.is_harmful) and curr.is_harmful,
            "escalation": prev.confidence < curr.confidence,
        }

    def score_content_safety(self, content: str) -> float:
        analysis = self.comprehensive_analysis(content)
        base_score = 1.0
        if analysis.is_harmful:
            base_score -= 0.5
        harmful_keywords = sum(1 for w in self.harmful_intents if w in content.lower())
        base_score -= harmful_keywords * 0.05
        negative_sentiment = self.analyze_sentiment(content).get("negative", 0)
        base_score -= negative_sentiment * 0.2
        return round(max(0.0, min(1.0, base_score)), 4)