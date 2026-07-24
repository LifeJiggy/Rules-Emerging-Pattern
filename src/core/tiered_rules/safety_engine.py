"""Safety Rule Engine - Tier 1 enforcement with automatic blocking."""
import logging
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum

from rules_emerging_pattern.models.rule import RuleTier, RuleEvaluationRequest, RuleSeverity, RuleContext
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken

logger = logging.getLogger(__name__)


class SafetyAction(str, Enum):
    BLOCK = "block"
    QUARANTINE = "quarantine"
    ESCALATE = "escalate"
    REDACT = "redact"
    WARN = "warn"


class SafetyCategory:
    def __init__(self, name: str, severity: RuleSeverity, action: SafetyAction,
                 patterns: List[str], regex_patterns: Optional[List[str]] = None,
                 exemptions: Optional[List[str]] = None,
                 description: str = "", educational_exempt: bool = False):
        self.name = name
        self.severity = severity
        self.action = action
        self.patterns = [p.lower() for p in patterns]
        self.regex_patterns = regex_patterns or []
        self.exemptions = [e.lower() for e in (exemptions or [])]
        self.description = description
        self.educational_exempt = educational_exempt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "action": self.action.value,
            "pattern_count": len(self.patterns),
            "regex_count": len(self.regex_patterns),
            "exemption_count": len(self.exemptions),
            "educational_exempt": self.educational_exempt,
            "description": self.description,
        }


class SafetyPatternMatch:
    def __init__(self, category: str, matched_text: str, severity: RuleSeverity,
                 action: SafetyAction, confidence: float, is_regex: bool = False,
                 position: Optional[int] = None):
        self.category = category
        self.matched_text = matched_text
        self.severity = severity
        self.action = action
        self.confidence = confidence
        self.is_regex = is_regex
        self.position = position
        self.timestamp = datetime.utcnow()

    def to_violation(self, context: Dict[str, Any], override_allowed: bool = False) -> Violation:
        action_taken_map = {
            SafetyAction.BLOCK: ActionTaken.BLOCK,
            SafetyAction.QUARANTINE: ActionTaken.QUARANTINE,
            SafetyAction.ESCALATE: ActionTaken.ESCALATE,
            SafetyAction.REDACT: ActionTaken.REDACT,
            SafetyAction.WARN: ActionTaken.WARNING,
        }
        return Violation(
            rule_id=f"safety_{self.category}",
            rule_name=f"Safety Rule: {self.category}",
            rule_tier=RuleTier.SAFETY,
            rule_severity=self.severity,
            violation_type=ViolationType.REGEX_MATCH if self.is_regex else ViolationType.KEYWORD_MATCH,
            matched_content=self.matched_text,
            matched_patterns=[self.matched_text],
            confidence_score=self.confidence,
            action_taken=action_taken_map.get(self.action, ActionTaken.BLOCK),
            blocked=self.action in (SafetyAction.BLOCK, SafetyAction.QUARANTINE),
            user_override_allowed=override_allowed,
            explanation=f"Safety violation detected: {self.category} (matched: {self.matched_text})",
            position_info={"position": self.position} if self.position is not None else {},
            context=context,
        )


class SafetyStats:
    def __init__(self):
        self.evaluation_count: int = 0
        self.block_count: int = 0
        self.quarantine_count: int = 0
        self.escalation_count: int = 0
        self.redact_count: int = 0
        self.warning_count: int = 0
        self.category_counts: Dict[str, int] = {}
        self.category_block_counts: Dict[str, int] = {}
        self.total_processing_time_ms: int = 0
        self.exemption_hits: int = 0
        self.false_positives_reported: int = 0

    def record_match(self, category: str, action: SafetyAction, processing_ms: int) -> None:
        self.evaluation_count += 1
        self.total_processing_time_ms += processing_ms
        self.category_counts[category] = self.category_counts.get(category, 0) + 1
        if action == SafetyAction.BLOCK:
            self.block_count += 1
            self.category_block_counts[category] = self.category_block_counts.get(category, 0) + 1
        elif action == SafetyAction.QUARANTINE:
            self.quarantine_count += 1
        elif action == SafetyAction.ESCALATE:
            self.escalation_count += 1
        elif action == SafetyAction.REDACT:
            self.redact_count += 1
        elif action == SafetyAction.WARN:
            self.warning_count += 1

    def get_summary(self) -> Dict[str, Any]:
        return {
            "evaluation_count": self.evaluation_count,
            "block_count": self.block_count,
            "quarantine_count": self.quarantine_count,
            "escalation_count": self.escalation_count,
            "redact_count": self.redact_count,
            "warning_count": self.warning_count,
            "category_counts": dict(self.category_counts),
            "category_block_counts": dict(self.category_block_counts),
            "avg_processing_time_ms": round(
                self.total_processing_time_ms / max(self.evaluation_count, 1), 2
            ),
            "exemption_hits": self.exemption_hits,
            "false_positives_reported": self.false_positives_reported,
            "total_processing_time_ms": self.total_processing_time_ms,
        }

    def report_false_positive(self) -> None:
        self.false_positives_reported += 1


class SafetyRuleEngine:
    """Tier 1 Safety Rule Engine with strict enforcement."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.tier = RuleTier.SAFETY
        self.config = config or {}
        self.stats = SafetyStats()
        self._compiled_regexes: Dict[str, re.Pattern] = {}
        self._categories: List[SafetyCategory] = []
        self._initialize_categories()
        self._compile_regexes()
        logger.info(
            "SafetyRuleEngine initialized with %d categories, %d total patterns",
            len(self._categories),
            sum(len(c.patterns) + len(c.regex_patterns) for c in self._categories),
        )

    def _initialize_categories(self) -> None:
        self._categories = [
            SafetyCategory(
                name="child_safety",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.BLOCK,
                patterns=[
                    "child exploitation", "child pornography", "child abuse material",
                    "underage content", "minor exploitation", "csam",
                    "child sexual abuse", "minor abuse", "child trafficking",
                    "exploitation of minors",
                ],
                regex_patterns=[
                    r"\b(minor|child|underage)\s+(abuse|exploit|porn|traffic)",
                    r"\bcsam\b",
                ],
                description="Content involving minors in exploitative contexts",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="dangerous_content",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.BLOCK,
                patterns=[
                    "how to make a bomb", "bomb making instructions", "explosive device",
                    "improvised explosive", "chemical weapon", "biological weapon",
                    "how to build a bomb", "pipe bomb", "suicide bombing instructions",
                    "weapon of mass destruction", "diy bomb", "explosive compound",
                    "ricin production", "sarin gas", "nerve agent synthesis",
                ],
                regex_patterns=[
                    r"\b(bomb|explosive|ied)\s+(making|build|create|instructions?|recipe)",
                    r"\b(chemical|biological|radiological)\s+weapon\s+(recipe|instructions?)",
                ],
                description="Content instructing creation of weapons or dangerous materials",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="weapons",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "create weapon", "weapon fabrication", "3d print gun",
                    "ghost gun instructions", "manufacture firearm", "assault weapon plans",
                    "auto sear", "machine gun conversion", "suppressor fabrication",
                    "undetectable firearm", "printed firearm", "homemade gun",
                    "weapon modification", "firearm conversion kit",
                ],
                regex_patterns=[
                    r"\b(3d.?print|manufacture|fabricat)\s+(firearm|gun|weapon|pistol|rifle)",
                    r"\bghost.?gun\s+(instructions?|plans?|build|kit)",
                ],
                description="Content about weapon creation or modification",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="malicious_code",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "malware code", "ransomware source", "virus creation",
                    "trojan horse code", "worm payload", "keylogger source",
                    "botnet code", "ddos payload", "exploit kit",
                    "shellcode payload", "rootkit source", "backdoor code",
                    "malicious macro", "dropper payload", "loader malware",
                ],
                regex_patterns=[
                    r"\b(ransomware|malware|trojan|worm|keylogger|botnet)\s+(source|code|payload|builder|kit)",
                    r"\bexploit\s+(kit|pack|framework)\s+(code|source|download)",
                ],
                description="Code or instructions for malware creation",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="hacking_tools",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "hacking tutorial illegal", "how to hack bank account",
                    "credit card fraud methods", "identity theft guide",
                    "phishing kit", "social engineering toolkit",
                    "account takeover method", "bypass authentication illegal",
                    "cracking passwords tutorial", "sql injection exploit guide",
                    "privilege escalation exploit", "zero day exploit sale",
                    "ransomware as a service", "ddos for hire",
                ],
                regex_patterns=[
                    r"\b(hack|crack|breach|bypass)\s+(bank|credit.?card|account|password|auth)",
                    r"\b(phishing|social.?engineering)\s+(kit|toolkit|template|guide)",
                ],
                description="Content promoting illegal hacking activities",
            ),
            SafetyCategory(
                name="terrorism",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.ESCALATE,
                patterns=[
                    "terrorist recruitment", "join terrorist organization",
                    "radicalization content", "extremist propaganda",
                    "terrorist financing", "lone wolf attack planning",
                    "mass casualty planning", "target selection terrorism",
                    "terrorist manifesto", "extremist ideology recruitment",
                ],
                regex_patterns=[
                    r"\b(terroris|extremis|radicaliz)\s+(recruit|propaganda|financing|planning)",
                    r"\b(mass.?shooting|mass.?casualty)\s+(plan|target|manifesto)",
                ],
                description="Content related to terrorism or extremist recruitment",
            ),
            SafetyCategory(
                name="self_harm",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.BLOCK,
                patterns=[
                    "how to commit suicide", "suicide methods", "self harm instructions",
                    "cutting tutorial", "how to self harm", "suicide pact",
                    "encourage suicide", "suicide challenge", "self injury methods",
                    "ending my life guide", "painless suicide",
                ],
                regex_patterns=[
                    r"\b(suicide|self.?harm|self.?injury)\s+(methods?|ways?|how|technique|guide|instructions?)",
                    r"\b(commit|attempt)\s+suicide\s+(methods?|ways?|guide)",
                ],
                description="Content about self-harm or suicide methods",
                educational_exempt=True,
                exemptions=[
                    "suicide prevention", "self harm resources", "mental health support",
                    "crisis hotline", "talk to someone",
                ],
            ),
            SafetyCategory(
                name="harassment",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "death threat", "kill you", "i will kill",
                    "targeted harassment", "doxing threat", "swatting threat",
                    "violent threat", "physical harm threat", "stalking threat",
                    "rape threat", "violent revenge",
                ],
                regex_patterns=[
                    r"\b(i.?ll|will)\s+(kill|hurt|harm|attack)\s+(you|your|them|everyone)",
                    r"\b(death|violent|physical)\s+threat",
                ],
                description="Harassment, threats, or targeted abuse",
            ),
            SafetyCategory(
                name="hate_speech",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "racial superiority", "white supremacist", "neo nazi",
                    "genocide advocacy", "ethnic cleansing", "racial purity",
                    "holocaust denial", "hate group recruitment", "supremacist ideology",
                    "incite racial violence", "religious persecution advocacy",
                ],
                regex_patterns=[
                    r"\b(white|black|racial?)\s+supremac",
                    r"\b(hate|incite)\s+(speech|violence|attack|crime)",
                    r"\b(genocide|ethnic.?cleansing)\s+(advoca|support|promot)",
                ],
                description="Hate speech or discriminatory content targeting groups",
            ),
            SafetyCategory(
                name="personal_data",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.REDACT,
                patterns=[
                    "social security number", "credit card number", "bank account details",
                    "passport number", "driver license number", "medical record id",
                    "national id number", "tax id number", "financial account number",
                    "insurance policy number", "biometric data dump",
                ],
                regex_patterns=[
                    r"\b\d{3}-\d{2}-\d{4}\b",
                    r"\b(?:\d[ -]*?){13,16}\b",
                    r"\b[A-Z]{2}\d{6}[A-Z]?\b",
                ],
                description="Personally identifiable information exposure",
                exemptions=[
                    "example ssn", "sample credit card", "test account",
                    "mock data", "placeholder ssn", "dummy data",
                ],
            ),
            SafetyCategory(
                name="credentials",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.REDACT,
                patterns=[
                    "api key exposed", "secret key leak", "password dump",
                    "database credentials leak", "aws secret key", "private key disclosure",
                    "oauth token exposed", "jwt secret leak", "encryption key leak",
                    "connection string leak", "auth token exposed",
                ],
                regex_patterns=[
                    r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?key)\s*[:=]\s*\S+",
                    r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+",
                    r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----",
                ],
                description="Exposed credentials or security tokens",
                exemptions=[
                    "example api key", "sample password", "example.com",
                    "test credentials", "placeholder key",
                ],
            ),
            SafetyCategory(
                name="pii_composite",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.REDACT,
                patterns=[
                    "full name and address", "name and social security",
                    "date of birth with ssn", "medical history with name",
                    "financial records personal", "address phone email combo",
                ],
                regex_patterns=[
                    r"\b[A-Z][a-z]+ [A-Z][a-z]+,\s*\d{3}-\d{2}-\d{4}\b",
                    r"\b\d{3}-\d{2}-\d{4}\s+\d{2}/\d{2}/\d{4}\b",
                ],
                description="Composite personally identifiable information",
            ),
            SafetyCategory(
                name="malware_distribution",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.BLOCK,
                patterns=[
                    "malware download link", "virus download", "ransomware download",
                    "trojan download", "worm download", "exploit download",
                    "payload download", "backdoor download",
                ],
                regex_patterns=[
                    r"\b(?:download|get|fetch)\s+(?:malware|ransomware|virus|trojan|worm|exploit)\s+(?:here|now|free|link)",
                    r"(?:https?://)?\S+\.(?:exe|dll|scr|bat|vbs|ps1)\s+(?:malware|virus|ransomware)",
                ],
                description="Links or instructions for malware distribution",
            ),
            SafetyCategory(
                name="fraud",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "advance fee fraud", "phishing scam template", "identity theft kit",
                    "fake check scam", "lottery scam template", "romance scam script",
                    "investment fraud scheme", "pyramid scheme pitch", "tax fraud method",
                    "insurance fraud guide", "credit repair scam",
                ],
                regex_patterns=[
                    r"\b(fraud|scam|phishing)\s+(kit|template|script|guide|method|scheme)",
                    r"\b(advance.?fee|lottery|romance|investment)\s+(fraud|scam)",
                ],
                description="Fraudulent schemes or scam content",
            ),
            SafetyCategory(
                name="drug_manufacturing",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "methamphetamine synthesis", "cocaine production", "heroin manufacturing",
                    "lsd synthesis guide", "mdma production", "fentanyl synthesis",
                    "drug lab instructions", "illicit drug manufacture", "amphetamine synthesis",
                    "mushroom cultivation illegal", "marijuana grow operation illegal",
                ],
                regex_patterns=[
                    r"\b(meth|cocaine|heroin|lsd|mdma|fentanyl)\s+(synthesis|manufactur|production|cook|recipe)",
                    r"\bdrug\s+(lab|manufactur|production|synthesis|cook)\s+(guide|instructions?)",
                ],
                description="Illicit drug manufacturing instructions",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="human_trafficking",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.ESCALATE,
                patterns=[
                    "human trafficking network", "trafficking victims sale",
                    "forced labor recruitment", "illegal adoption scheme",
                    "organ trafficking", "child trafficking network",
                    "smuggling humans for sale", "forced marriage arrangement",
                ],
                regex_patterns=[
                    r"\b(human|child|forced)\s+(trafficking|sale|smuggling|exploit)",
                    r"\btrafficking\s+(network|ring|operation|victim|recruit)",
                ],
                description="Human trafficking or forced labor content",
            ),
            SafetyCategory(
                name="violent_extremism",
                severity=RuleSeverity.CRITICAL,
                action=SafetyAction.ESCALATE,
                patterns=[
                    "violent jihad instructions", "lone wolf tactics",
                    "vehicle attack planning", "knife attack methodology",
                    "improvised weapon attack", "soft target selection",
                    "infrastructure attack planning", "crowd attack method",
                ],
                regex_patterns=[
                    r"\b(lone.?wolf|vehicle.?attack|soft.?target|infrastructure.?target)\s+(plan|method|tactic|guide)",
                    r"\b(attack|strike|target)\s+(planning|selection|methodology|tactic)",
                ],
                description="Violent extremist attack planning",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="cyberbullying",
                severity=RuleSeverity.MEDIUM,
                action=SafetyAction.WARN,
                patterns=[
                    "you are worthless", "nobody likes you", "kill yourself already",
                    "you should die", "the world is better without you",
                    "nobody wants you here", "you are a waste of space",
                ],
                regex_patterns=[
                    r"\b(you.?(?:are|r))\s+(worthless|useless|pathetic|disgusting|horrible|terrible)",
                    r"\b(nobody|no.?one)\s+(likes|wants|cares about)\s+you",
                ],
                description="Cyberbullying or targeted harassment of individuals",
                exemptions=[
                    "character dialogue", "fiction", "novel excerpt", "screenplay",
                    "lyrics", "satire", "parody",
                ],
            ),
            SafetyCategory(
                name="misinformation_harm",
                severity=RuleSeverity.MEDIUM,
                action=SafetyAction.WARN,
                patterns=[
                    "vaccine causes autism", "covid 19 hoax", "fake medicine cure",
                    "miracle cure scam", "anti vaxx conspiracy", "5g causes coronavirus",
                    "chem trails poisoning", "flat earth proof", "climate change hoax",
                    "election fraud conspiracy", "deep state control",
                ],
                regex_patterns=[
                    r"\b(vaccine|covid|5g|chem.?trail|climate)\s+(hoax|fake|scam|conspiracy|causes|cause)",
                    r"\b(anti.?vaxx|anti.?vaccine)\s+(conspiracy|truth|proof|evidence)",
                ],
                description="Harmful misinformation or conspiracy theories",
                exemptions=[
                    "debunking", "fact check", "myth busting", "actually the evidence shows",
                    "research indicates", "studies show",
                ],
            ),
            SafetyCategory(
                name="eating_disorder",
                severity=RuleSeverity.MEDIUM,
                action=SafetyAction.WARN,
                patterns=[
                    "pro ana tips", "pro anorexia", "pro bulimia",
                    "thinspiration", "thinspo", "anorexic tips",
                    "how to hide eating disorder", "purging methods",
                    "starvation tips", "extreme weight loss dangerous",
                ],
                regex_patterns=[
                    r"\b(pro.?ana|pro.?mia|thinspir|thinspo|ana.?tips|mia.?tips)\b",
                    r"\b(eating.?disorder|anorex|bulimi)\s+(tips?|methods?|technique|hack|secret)",
                ],
                description="Content promoting eating disorders",
                educational_exempt=True,
                exemptions=[
                    "recovery", "treatment", "help for", "support group",
                    "nutritionist", "therapy", "counseling",
                ],
            ),
            SafetyCategory(
                name="gambling_addiction",
                severity=RuleSeverity.MEDIUM,
                action=SafetyAction.WARN,
                patterns=[
                    "gambling addiction tips", "how to gamble more",
                    "gambling system guaranteed", "betting strategy sure win",
                    "risk everything gambling", "chase losses gambling",
                ],
                regex_patterns=[
                    r"\b(gambl|bet|casino)\s+(addiction|system|strategy|guaranteed|sure.?win|risk.?it.?all)",
                ],
                description="Content promoting harmful gambling behavior",
                exemptions=[
                    "responsible gambling", "gamble responsibly", "gambling addiction help",
                    "problem gambling support", "gamble aware",
                ],
            ),
            SafetyCategory(
                name="revenge_porn",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "explicit images revenge", "intimate photo leak",
                    "non consensual intimate", "private photos revenge",
                    "exposed nudes revenge", "leaked intimate content",
                ],
                regex_patterns=[
                    r"\b(revenge.?porn|non.?consensual.?intimate|intimate.?image.?abuse)\b",
                    r"\b(leak|expose|post)\s+(nudes?|intimate|private)\s+(photos?|images?|videos?|content)\s+(revenge|ex)",
                ],
                description="Non-consensual intimate content distribution",
            ),
            SafetyCategory(
                name="political_extremism",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.WARN,
                patterns=[
                    "overthrow government", "violent revolution call",
                    "assassination plot", "government target list",
                    "coups d etat planning", "insurrection planning",
                ],
                regex_patterns=[
                    r"\b(overthrow|violent.?revolut|coup|insurrection)\s+(plan|call|advoca|start|organize)",
                    r"\b(assassinate|kill|target)\s+(president|prime.?minister|senator|congress|governor|judge)",
                ],
                description="Content advocating political violence",
                educational_exempt=True,
            ),
            SafetyCategory(
                name="animal_cruelty",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "animal torture methods", "how to abuse animals",
                    "animal fighting ring", "dog fighting training",
                    "cockfighting guide", "animal sacrifice instructions",
                ],
                regex_patterns=[
                    r"\b(animal|pet|dog|cat)\s+(torture|abuse|cruelty|fight)\s+(methods?|guide|instructions?|tips?)",
                    r"\b(dog.?fight|animal.?fight|cock.?fight)\s+(train|breed|raise|guide)",
                ],
                description="Content depicting or promoting animal cruelty",
                educational_exempt=True,
                exemptions=[
                    "animal rescue", "animal welfare", "animal protection",
                    "humane society", "spca", "animal rights",
                ],
            ),
            SafetyCategory(
                name="illegal_drug_sale",
                severity=RuleSeverity.HIGH,
                action=SafetyAction.BLOCK,
                patterns=[
                    "buy cocaine online", "order heroin", "purchase meth",
                    "illegal drugs for sale", "buy prescription no prescription",
                    "dark web drug market", "cannabis delivery illegal",
                    "synthetic drugs for sale", "research chemicals buy",
                ],
                regex_patterns=[
                    r"\b(buy|order|purchase|sell)\s+(cocaine|heroin|meth|lsd|mdma|ecstasy|fentanyl|opioid)\s+(online|on.?line|cheap|legal)",
                    r"\b(dark.?web|darknet)\s+(drug|market|marketplace|shop|store)",
                ],
                description="Illegal drug sales or marketplace links",
            ),
        ]
        custom_categories = self.config.get("custom_categories", [])
        for cat_data in custom_categories:
            self._categories.append(SafetyCategory(
                name=cat_data.get("name", "custom"),
                severity=RuleSeverity(cat_data.get("severity", "high")),
                action=SafetyAction(cat_data.get("action", "block")),
                patterns=cat_data.get("patterns", []),
                regex_patterns=cat_data.get("regex_patterns", []),
                exemptions=cat_data.get("exemptions", []),
                description=cat_data.get("description", ""),
                educational_exempt=cat_data.get("educational_exempt", False),
            ))
        disabled = set(self.config.get("disabled_categories", []))
        self._categories = [c for c in self._categories if c.name not in disabled]

    def _compile_regexes(self) -> None:
        for category in self._categories:
            for regex in category.regex_patterns:
                try:
                    self._compiled_regexes[f"{category.name}:{regex}"] = re.compile(
                        regex, re.IGNORECASE
                    )
                except re.error as e:
                    logger.warning("Failed to compile regex for %s: %s", category.name, e)

    def _check_exemptions(
        self, content_lower: str, category: SafetyCategory, context: Optional[RuleContext]
    ) -> bool:
        for exemption in category.exemptions:
            if exemption.lower() in content_lower:
                self.stats.exemption_hits += 1
                logger.debug("Exemption '%s' matched for category '%s'", exemption, category.name)
                return True
        if category.educational_exempt:
            educational_indicators = [
                "educational purposes", "research purposes", "academic study",
                "for educational use", "training material", "security research",
                "penetration testing", "authorized testing", "academic paper",
                "this is a simulation", "demonstration only", "educational context",
                "for informational purposes", "awareness program", "safety training",
                "for authorized testing only", "ethical hacking course",
            ]
            for indicator in educational_indicators:
                if indicator in content_lower:
                    self.stats.exemption_hits += 1
                    logger.debug(
                        "Educational exemption matched for category '%s': '%s'",
                        category.name, indicator,
                    )
                    return True
        if context:
            effective = context.get_effective_context()
            exempt_domains = self.config.get("exempt_domains", [])
            if effective.get("domain") in exempt_domains:
                self.stats.exemption_hits += 1
                return True
            exempt_orgs = self.config.get("exempt_organizations", [])
            if effective.get("organization") in exempt_orgs:
                self.stats.exemption_hits += 1
                return True
            exempt_roles = self.config.get("exempt_roles", [])
            role = effective.get("user_role")
            if role and role in exempt_roles:
                self.stats.exemption_hits += 1
                return True
        return False

    def _scan_content(self, content: str, content_lower: str) -> List[SafetyPatternMatch]:
        matches: List[SafetyPatternMatch] = []
        seen_categories: Set[str] = set()
        for category in self._categories:
            if category.name in seen_categories:
                continue
            for pattern in category.patterns:
                idx = content_lower.find(pattern)
                if idx != -1:
                    confidence = 0.95
                    matches.append(SafetyPatternMatch(
                        category=category.name,
                        matched_text=content[idx:idx + len(pattern)],
                        severity=category.severity,
                        action=category.action,
                        confidence=confidence,
                        position=idx,
                    ))
                    seen_categories.add(category.name)
                    break
        for category in self._categories:
            if category.name in seen_categories:
                continue
            for regex_str in category.regex_patterns:
                key = f"{category.name}:{regex_str}"
                compiled = self._compiled_regexes.get(key)
                if compiled:
                    match = compiled.search(content)
                    if match:
                        confidence = 0.90
                        matches.append(SafetyPatternMatch(
                            category=category.name,
                            matched_text=match.group(),
                            severity=category.severity,
                            action=category.action,
                            confidence=confidence,
                            is_regex=True,
                            position=match.start(),
                        ))
                        seen_categories.add(category.name)
                        break
        return matches

    def _resolve_action(self, matches: List[SafetyPatternMatch]) -> SafetyAction:
        priority = {
            SafetyAction.ESCALATE: 0,
            SafetyAction.BLOCK: 1,
            SafetyAction.QUARANTINE: 2,
            SafetyAction.REDACT: 3,
            SafetyAction.WARN: 4,
        }
        if not matches:
            return SafetyAction.WARN
        return min((m.action for m in matches), key=lambda a: priority.get(a, 99))

    async def evaluate(self, request: RuleEvaluationRequest) -> ValidationResult:
        start_time = datetime.utcnow()
        content = request.content
        content_lower = content.lower()
        result = ValidationResult(
            valid=True,
            total_score=1.0,
            confidence=1.0,
            request_id=f"safety_{self.stats.evaluation_count}",
            content_hash=str(hash(content))[:16],
        )
        matches = self._scan_content(content, content_lower)
        category_context = request.context.get_effective_context() if request.context else {}
        filtered_matches: List[SafetyPatternMatch] = []
        matched_categories: Set[str] = set()
        for match in matches:
            if match.category in matched_categories:
                continue
            category_obj = next(
                (c for c in self._categories if c.name == match.category), None
            )
            if category_obj and self._check_exemptions(content_lower, category_obj, request.context):
                logger.info(
                    "Safety category '%s' exempted for content", match.category
                )
                continue
            filtered_matches.append(match)
            matched_categories.add(match.category)
        resolved_action = self._resolve_action(filtered_matches)
        for match in filtered_matches:
            override_allowed = match.action in (
                SafetyAction.WARN, SafetyAction.REDACT
            )
            violation = match.to_violation(
                context=category_context, override_allowed=override_allowed
            )
            result.violations.append(violation)
            if match.severity in (RuleSeverity.CRITICAL, RuleSeverity.HIGH):
                result.critical_violations.append(violation)
            if match.action == SafetyAction.WARN:
                result.warnings.append(violation)
            result.valid = result.valid and not violation.blocked
            self.stats.record_match(
                category=match.category,
                action=match.action,
                processing_ms=0,
            )
            log_level = (
                logger.warning if match.action in (SafetyAction.BLOCK, SafetyAction.QUARANTINE)
                else logger.info
            )
            log_level(
                "Safety %s: category='%s' action=%s severity=%s",
                "blocked" if violation.blocked else "detected",
                match.category,
                match.action.value,
                match.severity.value,
            )
        processing_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        result.processing_time_ms = processing_ms
        result.total_rules_evaluated = len(self._categories)
        result.rules_triggered = len(result.violations)
        logger.debug(
            "Safety evaluation completed: %d violations in %dms",
            len(result.violations), processing_ms,
        )
        return result

    def _get_consecutive_categories_for_summary(self) -> List[str]:
        return [c.name for c in self._categories]

    def get_safety_categories(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self._categories]

    def get_statistics(self) -> Dict[str, Any]:
        return self.stats.get_summary()

    def report_false_positive(self, category: Optional[str] = None) -> None:
        self.stats.report_false_positive()
        if category:
            logger.info("False positive reported for category '%s'", category)

    def add_custom_category(self, category_data: Dict[str, Any]) -> None:
        cat = SafetyCategory(
            name=category_data["name"],
            severity=RuleSeverity(category_data.get("severity", "high")),
            action=SafetyAction(category_data.get("action", "block")),
            patterns=category_data.get("patterns", []),
            regex_patterns=category_data.get("regex_patterns", []),
            exemptions=category_data.get("exemptions", []),
            description=category_data.get("description", ""),
            educational_exempt=category_data.get("educational_exempt", False),
        )
        self._categories.append(cat)
        for regex in cat.regex_patterns:
            try:
                self._compiled_regexes[f"{cat.name}:{regex}"] = re.compile(regex, re.IGNORECASE)
            except re.error as e:
                logger.warning("Failed to compile regex for %s: %s", cat.name, e)
        logger.info("Added custom safety category: %s", cat.name)

    def remove_category(self, name: str) -> bool:
        before = len(self._categories)
        self._categories = [c for c in self._categories if c.name != name]
        keys_to_remove = [k for k in self._compiled_regexes if k.startswith(f"{name}:")]
        for k in keys_to_remove:
            del self._compiled_regexes[k]
        removed = len(self._categories) < before
        if removed:
            logger.info("Removed safety category: %s", name)
        return removed

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config.update(config)
        self._categories.clear()
        self._compiled_regexes.clear()
        self._initialize_categories()
        self._compile_regexes()
        logger.info("SafetyRuleEngine configuration updated")

    def get_active_categories(self) -> List[str]:
        return [c.name for c in self._categories]

    def is_category_active(self, name: str) -> bool:
        return any(c.name == name for c in self._categories)

    def get_category_detail(self, name: str) -> Optional[Dict[str, Any]]:
        for c in self._categories:
            if c.name == name:
                return c.to_dict()
        return None

    def get_patterns_for_category(self, name: str) -> Dict[str, Any]:
        for c in self._categories:
            if c.name == name:
                return {
                    "keywords": list(c.patterns),
                    "regex": list(c.regex_patterns),
                    "exemptions": list(c.exemptions),
                }
        return {}

    def get_enforcement_threshold(self) -> float:
        return self.config.get("enforcement_threshold", 0.8)

    def get_max_actions_per_evaluation(self) -> int:
        return self.config.get("max_actions_per_evaluation", 50)

    def get_action_counts(self) -> Dict[str, int]:
        return {
            "block": self.stats.block_count,
            "quarantine": self.stats.quarantine_count,
            "escalate": self.stats.escalation_count,
            "redact": self.stats.redact_count,
            "warn": self.stats.warning_count,
        }

    def reset_statistics(self) -> None:
        self.stats = SafetyStats()
        logger.info("SafetyRuleEngine statistics reset")

    def get_category_statistics(self) -> Dict[str, Dict[str, int]]:
        result = {}
        all_categories = set(self.stats.category_counts.keys())
        all_categories.update(c.name for c in self._categories)
        for cat_name in sorted(all_categories):
            result[cat_name] = {
                "total_matches": self.stats.category_counts.get(cat_name, 0),
                "block_count": self.stats.category_block_counts.get(cat_name, 0),
                "is_active": self.is_category_active(cat_name),
            }
        return result

    def get_exemptions_applied(self) -> int:
        return self.stats.exemption_hits

    def get_false_positive_count(self) -> int:
        return self.stats.false_positives_reported
