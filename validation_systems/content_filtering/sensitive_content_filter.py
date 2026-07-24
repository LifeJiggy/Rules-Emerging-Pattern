"""
Sensitive content filter - regex-based pattern detection for medical, financial,
legal, political, and other sensitive content categories with multi-language
support, context-aware filtering, and statistical tracking.
"""

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from rules_emerging_pattern.models.rule import Rule, RuleTier, RuleType, RuleSeverity, RulePattern
from rules_emerging_pattern.models.validation import ValidationResult, Violation, ViolationType, ActionTaken
from rules_emerging_pattern.models.conflict import RuleConflict, ConflictType

logger = logging.getLogger(__name__)


class SensitiveCategory(str, Enum):
    MEDICAL = "medical"
    FINANCIAL = "financial"
    LEGAL = "legal"
    POLITICAL = "political"
    RELIGIOUS = "religious"
    SEXUAL = "sexual"
    VIOLENCE = "violence"
    DRUGS = "drugs"
    DISCRIMINATION = "discrimination"
    PERSONAL_DATA = "personal_data"
    TRADE_SECRET = "trade_secret"
    CLASSIFIED = "classified"
    CRIMINAL = "criminal"
    ETHICS = "ethics"
    CUSTOM = "custom"


class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MatchStrategy(str, Enum):
    EXACT = "exact"
    REGEX = "regex"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    CONTEXTUAL = "contextual"
    HYBRID = "hybrid"


@dataclass
class SensitivePattern:
    pattern_id: str
    category: SensitiveCategory
    pattern: str
    strategy: MatchStrategy = MatchStrategy.REGEX
    description: str = ""
    severity: SensitivityLevel = SensitivityLevel.MEDIUM
    weight: float = 1.0
    languages: List[str] = field(default_factory=lambda: ["en"])
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compile_pattern(self) -> Optional[re.Pattern]:
        if self.strategy == MatchStrategy.REGEX:
            try:
                return re.compile(self.pattern, re.IGNORECASE | re.UNICODE)
            except re.error as e:
                logger.warning("Failed to compile pattern %s: %s", self.pattern_id, e)
                return None
        return None


@dataclass
class WhitelistEntry:
    text: str
    category: Optional[SensitiveCategory] = None
    reason: str = ""
    created_by: str = "system"
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class ExemptionRule:
    exemption_id: str
    description: str
    category: Optional[SensitiveCategory] = None
    pattern_ids: List[str] = field(default_factory=list)
    condition: Optional[Callable[[str, Dict[str, Any]], bool]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class SensitiveMatch:
    pattern_id: str
    category: SensitiveCategory
    matched_text: str
    start_pos: int
    end_pos: int
    confidence: float
    severity: SensitivityLevel
    score: float
    language: str = "en"
    context_before: str = ""
    context_after: str = ""
    strategy: MatchStrategy = MatchStrategy.REGEX
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionStats:
    total_evaluations: int = 0
    total_detections: int = 0
    total_blocks: int = 0
    total_warnings: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    detection_rate: float = 0.0
    false_positive_rate: float = 0.0
    avg_confidence: float = 0.0
    category_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    severity_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    language_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    peak_hours: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    total_processing_time_ms: int = 0
    avg_processing_time_ms: float = 0.0
    last_evaluated: Optional[datetime] = None
    first_evaluated: Optional[datetime] = None
    recent_detections: deque = field(default_factory=lambda: deque(maxlen=1000))

    def record_evaluation(self, processing_time_ms: int, detections: List[SensitiveMatch],
                          blocked: bool = False, warned: bool = False) -> None:
        self.total_evaluations += 1
        self.total_processing_time_ms += processing_time_ms
        self.avg_processing_time_ms = self.total_processing_time_ms / self.total_evaluations

        now = datetime.utcnow()
        self.last_evaluated = now
        if self.first_evaluated is None:
            self.first_evaluated = now

        if detections:
            self.total_detections += len(detections)
            for match in detections:
                self.category_counts[match.category.value] += 1
                self.severity_counts[match.severity.value] += 1
                self.language_counts[match.language] += 1
                self.recent_detections.append({
                    "timestamp": now.isoformat(),
                    "category": match.category.value,
                    "severity": match.severity.value,
                    "confidence": match.confidence,
                    "score": match.score,
                })

        date_key = now.strftime("%Y-%m-%d")
        self.daily_counts[date_key] += 1

        hour_key = now.hour
        self.peak_hours[hour_key] += 1

        if blocked:
            self.total_blocks += 1
        if warned:
            self.total_warnings += 1

        if self.total_detections > 0:
            self.detection_rate = self.total_detections / self.total_evaluations
        if self.total_detections + self.false_positives > 0:
            self.false_positive_rate = self.false_positives / (self.total_detections + self.false_positives)

    def record_false_positive(self) -> None:
        self.false_positives += 1
        if self.total_detections + self.false_positives > 0:
            self.false_positive_rate = self.false_positives / (self.total_detections + self.false_positives)

    def record_false_negative(self) -> None:
        self.false_negatives += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "total_detections": self.total_detections,
            "total_blocks": self.total_blocks,
            "total_warnings": self.total_warnings,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "detection_rate": round(self.detection_rate, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "category_counts": dict(self.category_counts),
            "severity_counts": dict(self.severity_counts),
            "language_counts": dict(self.language_counts),
            "peak_hours": dict(self.peak_hours),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
            "first_evaluated": self.first_evaluated.isoformat() if self.first_evaluated else None,
        }

    def reset(self) -> None:
        self.total_evaluations = 0
        self.total_detections = 0
        self.total_blocks = 0
        self.total_warnings = 0
        self.false_positives = 0
        self.false_negatives = 0
        self.detection_rate = 0.0
        self.false_positive_rate = 0.0
        self.avg_confidence = 0.0
        self.category_counts.clear()
        self.severity_counts.clear()
        self.daily_counts.clear()
        self.language_counts.clear()
        self.peak_hours.clear()
        self.total_processing_time_ms = 0
        self.avg_processing_time_ms = 0.0
        self.last_evaluated = None
        self.first_evaluated = None
        self.recent_detections.clear()


SEVERITY_WEIGHTS = {
    SensitivityLevel.LOW: 0.2,
    SensitivityLevel.MEDIUM: 0.5,
    SensitivityLevel.HIGH: 0.8,
    SensitivityLevel.CRITICAL: 1.0,
}

LANGUAGE_PATTERNS = {
    "en": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-]+$'),
    "es": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-áéíóúüñ]+$'),
    "fr": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-àâçéèêëîïôùûü]+$'),
    "de": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-äöüß]+$'),
    "it": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-àèéìòù]+$'),
    "pt": re.compile(r'^[a-zA-Z0-9\s.,!?\'"-áâãàçéêíóôõúü]+$'),
    "ru": re.compile(r'^[а-яА-Яa-zA-Z0-9\s.,!?\'"-]+$'),
    "zh": re.compile(r'^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9\s.,!?]+$'),
    "ja": re.compile(r'^[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fffa-zA-Z0-9\s.,!?]+$'),
    "ar": re.compile(r'^[\u0600-\u06ffa-zA-Z0-9\s.,!?\'"-]+$'),
}

DEFAULT_SENSITIVE_PATTERNS: Dict[SensitiveCategory, List[Dict[str, Any]]] = {
    SensitiveCategory.MEDICAL: [
        {"pattern": r'\b(?:diagnosis|prognosis|treatment|prescription|dosage|surgery|symptom|disease|disorder|condition|therapy|medication|vaccine|immunization|hospitalization|clinical|patient|doctor|physician|surgeon|nurse|specialist|consultation|referral|admission|discharge|medical\s*record|health\s*history|family\s*history|allergy|intolerance|side\s*effect|contraindication|complication|prognosis|diagnosis|pathology|radiology|oncology|cardiology|neurology|psychiatry|dermatology|pediatrics|gynecology|obstetrics|orthopedics|ophthalmology|otolaryngology|urology|nephrology|gastroenterology|pulmonology|endocrinology|rheumatology|immunology|hematology|infectious\s*disease|emergency|intensive\s*care|palliative|hospice|rehabilitation|physical\s*therapy|occupational\s*therapy|speech\s*therapy|mental\s*health|counseling|psychotherapy|psychiatrist|psychologist|therapist|counselor)\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.0},
        {"pattern": r'\b(?:HIV|AIDS|cancer|tumor|malignant|benign|metastasis|leukemia|lymphoma|carcinoma|sarcoma|melanoma|glioma|meningitis|sepsis|septic|aneurysm|embolism|thrombosis|stroke|infarction|ischemia|hemorrhage|arrhythmia|cardiac\s*arrest|myocardial|infarct|failure\s*\(organ\)|transplant|dialysis|chemotherapy|radiation|immunotherapy|biopsy|autopsy|amputation|resection|excision|implant|prosthesis|stent|graft|shunt|bypass|pacemaker|defibrillator|catheter|intubation|ventilator|incubation|quarantine|isolation|biohazard|contagious|infectious|epidemic|pandemic|outbreak|endemic|zoonotic|vector-borne|airborne|bloodborne|nosocomial|opportunistic|resistant|superbug|antibiotic|antiviral|antifungal|antiparasitic|analgesic|anesthetic|antidepressant|antipsychotic|anxiolytic|sedative|hypnotic|stimulant|narcotic|opioid|controlled\s*substance|prescription\s*drug|over-the-counter|generic|brand-name|dosage|titration|withdrawal|tolerance|dependence|addiction|abuse|overdose|toxicity|poisoning|intoxication|allergic\s*reaction|anaphylaxis|angioedema|urticaria|rash|itching|swelling|difficulty\s*breathing|wheezing|cough|fever|chills|fatigue|weakness|dizziness|nausea|vomiting|diarrhea|constipation|abdominal\s*pain|chest\s*pain|shortness\s*of\s*breath|palpitations|syncope|seizure|convulsion|tremor|paralysis|numbness|tingling|vision\s*changes|hearing\s*loss|tinnitus|vertigo|confusion|disorientation|hallucination|delusion|paranoia|mania|depression|anxiety|panic|phobia|obsession|compulsion|eating\s*disorder|personality\s*disorder|bipolar|schizophrenia|autism|ADHD|PTSD|OCD|insomnia|sleep\s*apnea|narcolepsy)\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 1.5},
        {"pattern": r'\b(?:\d{2,3}/\d{2,3}/\d{2,4}\s*(?:mg|mcg|g|ml|IU|mEq|tablet|capsule|injection|solution|suspension|cream|ointment|patch|drop|spray|inhaler|suppository|implant|device))\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.2},
    ],
    SensitiveCategory.FINANCIAL: [
        {"pattern": r'\b(?:credit\s*card|debit\s*card|bank\s*account|routing\s*number|account\s*number|sort\s*code|iban|swift|bic|paypal|venmo|cashapp|zelle|wire\s*transfer|ach|direct\s*deposit|payment\s*method|billing\s*address|billing\s*information|financial\s*statement|bank\s*statement|transaction\s*history|balance\s*inquiry|credit\s*report|credit\s*score|fico|credit\s*limit|interest\s*rate|apr|annual\s*percentage|loan\s*agreement|mortgage|refinance|foreclosure|bankruptcy|insolvency|liquidation|receivership|audit|tax\s*return|w2|w-2|1099|tax\s*id|ein|ssn|social\s*security|itin|passport\s*number|driver\s*license|investment|portfolio|stock|bond|mutual\s*fund|etf|retirement|401k|ira|roth|pension|annuity|dividend|coupon|yield|principal|balance|overdraft|insufficient\s*funds|nsf|fee|penalty|chargeback|dispute|fraud|unauthorized|suspicious\s*activity|identity\s*theft|phishing|scam|breach|compromise|hack|cyber\s*attack|ransomware|malware|virus|trojan|keylogger|spyware|adware|phishing|spear\s*phishing|whaling|vishing|smishing|social\s*engineering|man-in-the-middle|session\s*hijacking|cookie\s*theft)\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 1.5},
        {"pattern": r'\b(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 2.0},
        {"pattern": r'\b(?:US\d{9}|GB\d{2}[A-Z]{2}\d{6}|\d{6}\s?\d{6}\s?\d{2})\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.3},
    ],
    SensitiveCategory.LEGAL: [
        {"pattern": r'\b(?:attorney-client\s*privilege|legal\s*advice|legal\s*opinion|confidential\s*communication|work\s*product|litigation|lawsuit|settlement|arbitration|mediation|deposition|testimony|affidavit|subpoena|summons|complaint|answer|motion|brief|memorandum|discovery|interrogatory|request\s*for\s*production|request\s*for\s*admission|exhibit|evidence|hearing|trial|verdict|judgment|appeal|remand|reversal|affirm|dismiss|summary\s*judgment|class\s*action|indictment|arraignment|plea|conviction|acquittal|sentence|probation|parole|pardon|expungement|sealing|non-disclosure|confidentiality|non-compete|non-solicitation|intellectual\s*property|copyright|trademark|patent|trade\s*secret|proprietary|confidential|classified|top\s*secret|eyes\s*only|need\s*to\s*know|privileged|attorney\s*work\s*product|legal\s*hold|preservation|spoliation|sanctions|contempt|injunction|restraining\s*order|protective\s*order|gag\s*order|sealing\s*order)\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.3},
        {"pattern": r'\b(?:plaintiff|defendant|petitioner|respondent|appellant|appellee|cross-claimant|cross-respondent|third-party|intervenor|amicus|pro\s*se|pro\s*bono|contingency|retainer|hourly|flat\s*fee|statutory|regulatory|compliance|audit\s*letter|legal\s*hold|litigation\s*hold|preservation\s*notice|cease\s*and\s*desist|demand\s*letter|notice\s*of\s*default|notice\s*of\s*termination|notice\s*of\s*breach|cure\s*notice|right\s*to\s*cure|acceleration|forbearance|workout|restructuring|reorganization|chapter\s*11|chapter\s*7|chapter\s*13|bankruptcy\s*court|adversary\s*proceeding|proof\s*of\s*claim|automatic\s*stay|relief\s*from\s*stay|adequate\s*protection|cram\s*down|plan\s*of\s*reorganization|disclosure\s*statement|ballot|confirmation|plan\s*administrator|trustee|examiner|creditor\s*committee|equity\s*committee|unsecured|secured|priority|administrative|general\s*unsecured|subordinated|guaranty|indemnity|hold\s*harmless|limitation\s*of\s*liability|waiver|severability|entire\s*agreement|integration|amendment|modification|assignment|delegation|successors|assigns|force\s*majeure|governing\s*law|jurisdiction|venue|arbitration|class\s*action\s*waiver|jury\s*waiver|notice|counterpart|electronic\s*signature|signature\s*block|execution|delivery|acceptance|approval|consent|authorization|ratification|confirmation|certification|acknowledgment|representation|warranty|covenant|condition|obligation|right|remedy|default|breach|termination|expiration|renewal|extension|survival)\b',
         "severity": SensitivityLevel.MEDIUM, "weight": 0.8},
    ],
    SensitiveCategory.POLITICAL: [
        {"pattern": r'\b(?:extremist|radical|terrorist|terrorism|violent\s*extremism|hate\s*group|white\s*supremacist|neo-nazi|fascist|communist|anarchist|militia|insurgent|guerrilla|paramilitary|jihadist|fundamentalist|separatist|sectarian|militant|activist|protest|demonstration|riot|civil\s*unrest|insurrection|coup|rebellion|revolution|overthrow|subversion|sedition|treason|espionage|spy|traitor|collaborator|defector|double\s*agent|mole|asset|informant|whistleblower|leak|expose|cover-up|conspiracy|cover\s*operation|black\s*ops|covert|clandestine|undercover|infiltrate|infiltration|surveillance|monitoring|wiretap|intercept|bug|tracker|tracking|sting\s*operation|entrapment|provocation|agent\s*provocateur|false\s*flag|psyop|disinformation|misinformation|propaganda|agitprop|fearmongering|dog\s*whistle|coded\s*language\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.2},
    ],
    SensitiveCategory.RELIGIOUS: [
        {"pattern": r'\b(?:blasphemy|heresy|apostasy|sacrilege|profane|desecrate|defile|unclean|impure|sinful|wicked|evil|damned|condemned|excommunicated|anathema|infidel|unbeliever|heathen|pagan|idolater|false\s*prophet|false\s*god|false\s*doctrine|false\s*teaching|cult|sect|heresy|schism|apostate|heretic|schismatic|renegade|defector|apostate|nonbeliever|godless|ungodly|irreligious|secular|atheist|agnostic|freethinker|rationalist|humanist|materialist|nihilist|existentialist|pantheist|polytheist|monotheist|henotheist|deist|theist)\b',
         "severity": SensitivityLevel.MEDIUM, "weight": 0.7},
    ],
    SensitiveCategory.SEXUAL: [
        {"pattern": r'\b(?:sexual\s*assault|sexual\s*abuse|sexual\s*harassment|sexual\s*exploitation|sexual\s*violence|rape|molestation|pedophilia|incest|pornography|obscenity|indecency|lewd|explicit\s*content|adult\s*content|mature\s*content|nsfw|not\s*safe\s*for\s*work|explicit\s*language|graphic\s*content|violent\s*content|gore|blood|violence|torture|abuse|cruelty|inhumane|degrading|humiliating|exploitation|trafficking|prostitution|solicitation|escort|massage\s*parlor|brothel|strip\s*club|adult\s*entertainment|xxx|erotic|fetish|kink|bdsm|dominant|submissive|master\s*slave|bondage|discipline|sadism|masochism|exhibitionism|voyeurism|fetishism|transvestic|transsexual|transgender|gender\s*identity|sexual\s*orientation|homosexual|heterosexual|bisexual|asexual|pansexual|queer|lgbtq|lgbt|ally|pride|rainbow)\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.3},
    ],
    SensitiveCategory.VIOLENCE: [
        {"pattern": r'\b(?:murder|kill|assassinate|execute|massacre|slaughter|butcher|homicide|manslaughter|genocide|ethnic\s*cleansing|war\s*crime|crime\s*against\s*humanity|atrocity|mass\s*killing|mass\s*shooting|school\s*shooting|active\s*shooter|terrorist\s*attack|bombing|explosion|improvised\s*explosive\s*device|ied|suicide\s*bomb|car\s*bomb|truck\s*ramming|knife\s*attack|stabbing|shooting|gunfire|gunshot|firearm|weapon|assault\s*rifle|machine\s*gun|submachine\s*gun|pistol|revolver|shotgun|rifle|sniper|explosive|grenade|mine|booby\s*trap|ambush|attack|assault|battery|strangle|suffocate|drown|poison|stab|shoot|bludgeon|beat|torture|maim|cripple|disable|incapacitate|subdue|restrain|handcuff|shackle|chain|gag|bind|tie|confinement|imprisonment|detention|captivity|hostage|kidnapping|abduction|ransom|extortion|blackmail|threat|intimidation|coercion|duress|harassment|stalking|cyberstalking|doxing|swatting|revenge\s*porn|nonconsensual\s*pornography|deepfake\s*pornography|image\s*abuse)\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 1.8},
    ],
    SensitiveCategory.DRUGS: [
        {"pattern": r'\b(?:controlled\s*substance|illegal\s*drug|narcotic|opioid|opiate|heroin|cocaine|crack|methamphetamine|crystal\s*meth|amphetamine|mdma|ecstasy|lsd|acid|psilocybin|magic\s*mushroom|peyote|mescaline|ayahuasca|dmt|ketamine|ghb|rohypnol|date\s*rape\s*drug|fentanyl|oxycodone|hydrocodone|morphine|codeine|meperidine|methadone|buprenorphine|naloxone|naltrexone|suboxone|subutex|methadone|vicodin|percocet|oxycontin|dilaudid|demerol|fentanyl\s*patches|sufentanil|remifentanil|carfentanil|designer\s*drug|synthetic\s*cannabinoid|k2|spice|synthetic\s*cathinone|bath\s*salts|flakka|alpha-pvp|research\s*chemical|nootropic|smart\s*drug|cognitive\s*enhancer|steroid|anabolic|performance\s*enhancing|doping|blood\s*doping|erectile\s*dysfunction|viagra|cialis|levitra|staxyn|stendra|vardenafil|tadalafil|sildenafil|prescription\s*fraud|doctor\s*shopping|pharmacy\s*hopping|pill\s*mill|online\s*pharmacy|rogue\s*pharmacy|counterfeit\s*drugs|bootleg|black\s*market|illicit|illegal|unlicensed|unregistered|unapproved|experimental|investigational|off-label|compounding|adulterated|contaminated|expired|recalled|defective|dangerous|unsafe|harmful|toxic|lethal|fatal|deadly)\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.2},
    ],
    SensitiveCategory.DISCRIMINATION: [
        {"pattern": r'\b(?:racism|racist|sexism|sexist|ageism|ageist|ableism|ableist|homophobia|homophobic|biphobia|biphobic|transphobia|transphobic|islamophobia|islamophobic|antisemitism|antisemitic|xenophobia|xenophobic|classism|classist|elitism|elitist|nativism|nativist|nationalism|nationalist|supremacy|supremacist|bigotry|bigot|prejudice|discrimination|stereotype|stigmatize|marginalize|oppress|suppress|persecute|victimize|scapegoat|demonize|dehumanize|otherize|exclude|segregate|ghettoize|apartheid|caste|untouchable|dalit|burakumin|romanip|roma|gypsy|traveler|nomad|indigenous|native|aboriginal|first\s*nation|tribe|tribal|ethnic|racial|color|creed|religion|national\s*origin|ancestry|citizenship|immigration|migrant|refugee|asylum|displaced|stateless|alien|foreigner|outsider|newcomer|settler|colonizer|colonist\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 1.8},
    ],
    SensitiveCategory.PERSONAL_DATA: [
        {"pattern": r'\b(?:\d{3}-\d{2}-\d{4}|\d{9})\b',
         "severity": SensitivityLevel.CRITICAL, "weight": 2.0},
        {"pattern": r'\b(?:email|e-mail|phone|telephone|mobile|cell|address|street|city|state|zip|postal|country|nationality|citizenship|passport|visa|id\s*card|driver\s*license|license\s*plate|vin|vehicle\s*id|serial\s*number|model\s*number|account\s*number|customer\s*id|user\s*id|member\s*id|policy\s*number|claim\s*number|order\s*number|invoice\s*number|receipt\s*number|confirmation\s*number|tracking\s*number|reference\s*number|confirmation\s*code|verification\s*code|access\s*code|pin|password|passcode|security\s*code|cvv|cvc|expiration\s*date|valid\s*through|effective\s*date|date\s*of\s*birth|birth\s*date|age|gender|sex|marital\s*status|occupation|employer|income|salary|wage|compensation|benefits|insurance|coverage|deductible|copay|coinsurance|out-of-pocket|maximum|limit|lifetime|annual|monthly|weekly|daily|hourly|rate|pay|wage|salary|bonus|commission|tips|gratuity|overtime|shift\s*differential|hazard\s*pay|severance|pension|retirement|profit\s*sharing|stock\s*option|equity|rsu|stock\s*award|bonus\s*plan|incentive\s*plan|commission\s*plan|compensation\s*plan|benefits\s*plan|health\s*insurance|dental\s*insurance|vision\s*insurance|life\s*insurance|disability\s*insurance|long-term\s*care|accident\s*insurance|cancer\s*insurance|critical\s*illness|hospital\s*indemnity|supplemental\s*insurance|medicare|medicaid|social\s*security|disability|unemployment|workers\s*comp|leave\s*of\s*absence|fmla|sick\s*leave|vacation|pto|personal\s*day|holiday|floating\s*holiday|sabbatical|parental\s*leave|maternity\s*leave|paternity\s*leave|family\s*leave|bereavement|jury\s*duty|military\s*leave|educational\s*leave|training|development|tuition\s*reimbursement|certification|license|professional\s*development|continuing\s*education|conference|seminar|workshop|webinar|course|class|program|degree|diploma|certificate|credential|qualification|skill|competency|proficiency|expertise|knowledge|experience|background|history|record|file|profile|dossier|portfolio|resume|cv|curriculum\s*vitae|application|enrollment|registration|subscription|membership|affiliation|association|organization|society|institute|foundation|corporation|company|firm|enterprise|business|establishment|agency|bureau|department|division|branch|office|location|site|facility|plant|factory|warehouse|distribution\s*center|headquarters|regional|national|international|global|worldwide|multinational|conglomerate|holding|subsidiary|affiliate|partner|joint\s*venture|consortium|alliance|network|franchise|licensee|franchisee|dealer|distributor|reseller|retailer|wholesaler|supplier|vendor|contractor|consultant|advisor|broker|agent|representative|manager|director|executive|officer|president|ceo|cfo|coo|cto|cmo|chief|vp|svp|evp|avp|head|lead|senior|junior|associate|assistant|coordinator|specialist|analyst|engineer|developer|architect|designer|writer|editor|producer|director|administrator|supervisor|lead|foreman|technician|operator|clerk|assistant|aide|helper|worker|employee|staff|personnel|human\s*resources|hr|talent|recruiting|hiring|onboarding|orientation|training|development|performance|review|appraisal|evaluation|assessment|rating|ranking|score|grade|level|band|tier|category|classification|job\s*title|position|role|function|responsibility|duty|task|assignment|project|initiative|program|portfolio|account|client|customer|partner|vendor|supplier|contractor|consultant|temp|intern|apprentice|trainee|volunteer|outsource|offshore|onshore|nearshore|remote|telecommute|virtual|distributed|hybrid|flexible|part-time|full-time|temporary|permanent|contract|consulting|freelance|gig|side\s*hustle|moonlight|second\s*job|supplemental|additional|extra|overtime)\b',
         "severity": SensitivityLevel.HIGH, "weight": 1.0},
    ],
}


class SensitiveContentFilter:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logger
        self.config = config or {}
        self.filter_id = str(uuid.uuid4())[:8]
        self._patterns: Dict[str, SensitivePattern] = {}
        self._compiled_patterns: Dict[str, Optional[re.Pattern]] = {}
        self._categories: Dict[SensitiveCategory, List[str]] = defaultdict(list)
        self._whitelist: List[WhitelistEntry] = []
        self._exemptions: Dict[str, ExemptionRule] = {}
        self._context_rules: Dict[str, Dict[str, Any]] = {}
        self._stats = DetectionStats()
        self._language_detection_enabled = self.config.get("enable_language_detection", True)
        self._default_threshold = self.config.get("default_threshold", 0.5)
        self._thresholds: Dict[SensitiveCategory, float] = {}
        self._severity_scores: Dict[SensitivityLevel, float] = {
            SensitivityLevel.LOW: 1,
            SensitivityLevel.MEDIUM: 5,
            SensitivityLevel.HIGH: 15,
            SensitivityLevel.CRITICAL: 50,
        }
        self._max_score = self.config.get("max_score", 100)
        self._block_threshold = self.config.get("block_threshold", 50)
        self._warn_threshold = self.config.get("warn_threshold", 20)
        self._context_window = self.config.get("context_window", 50)
        self._enable_context_analysis = self.config.get("enable_context_analysis", True)
        self._version = "2.0.0"

        self._init_default_patterns()
        self.logger.info("SensitiveContentFilter initialized (id=%s, version=%s, patterns=%d)",
                         self.filter_id, self._version, len(self._patterns))

    def _init_default_patterns(self) -> None:
        for category, patterns in DEFAULT_SENSITIVE_PATTERNS.items():
            for idx, p in enumerate(patterns):
                pattern_id = f"{category.value}_{idx}_{uuid.uuid4().hex[:6]}"
                sp = SensitivePattern(
                    pattern_id=pattern_id,
                    category=category,
                    pattern=p["pattern"],
                    strategy=MatchStrategy.REGEX,
                    severity=p.get("severity", SensitivityLevel.MEDIUM),
                    weight=p.get("weight", 1.0),
                    description=f"Default {category.value} pattern {idx}",
                    is_active=True,
                )
                self._patterns[pattern_id] = sp
                self._compiled_patterns[pattern_id] = sp.compile_pattern()
                self._categories[category].append(pattern_id)

    def add_pattern(self, category: SensitiveCategory, pattern: str,
                    strategy: MatchStrategy = MatchStrategy.REGEX,
                    severity: SensitivityLevel = SensitivityLevel.MEDIUM,
                    weight: float = 1.0,
                    description: str = "",
                    languages: Optional[List[str]] = None,
                    metadata: Optional[Dict[str, Any]] = None) -> SensitivePattern:
        pattern_id = f"custom_{uuid.uuid4().hex[:12]}"
        sp = SensitivePattern(
            pattern_id=pattern_id,
            category=category,
            pattern=pattern,
            strategy=strategy,
            severity=severity,
            weight=weight,
            description=description or f"Custom {category.value} pattern",
            languages=languages or ["en"],
            is_active=True,
            metadata=metadata or {},
        )
        self._patterns[pattern_id] = sp
        self._compiled_patterns[pattern_id] = sp.compile_pattern()
        self._categories[category].append(pattern_id)
        self.logger.info("Added pattern %s to category %s", pattern_id, category.value)
        return sp

    def remove_pattern(self, pattern_id: str) -> bool:
        if pattern_id not in self._patterns:
            return False
        sp = self._patterns[pattern_id]
        category = sp.category
        self._patterns.pop(pattern_id, None)
        self._compiled_patterns.pop(pattern_id, None)
        if category in self._categories and pattern_id in self._categories[category]:
            self._categories[category].remove(pattern_id)
        self.logger.info("Removed pattern %s from category %s", pattern_id, category.value)
        return True

    def update_pattern(self, pattern_id: str, **updates) -> Optional[SensitivePattern]:
        if pattern_id not in self._patterns:
            return None
        sp = self._patterns[pattern_id]
        for key, value in updates.items():
            if hasattr(sp, key) and key != "pattern_id":
                setattr(sp, key, value)
        if "pattern" in updates:
            self._compiled_patterns[pattern_id] = sp.compile_pattern()
        sp.metadata["updated_at"] = datetime.utcnow().isoformat()
        self.logger.info("Updated pattern %s", pattern_id)
        return sp

    def get_pattern(self, pattern_id: str) -> Optional[SensitivePattern]:
        return self._patterns.get(pattern_id)

    def list_patterns(self, category: Optional[SensitiveCategory] = None,
                      active_only: bool = False) -> List[SensitivePattern]:
        patterns = list(self._patterns.values())
        if category:
            patterns = [p for p in patterns if p.category == category]
        if active_only:
            patterns = [p for p in patterns if p.is_active]
        return patterns

    def get_categories(self) -> List[SensitiveCategory]:
        return list(SensitiveCategory)

    def add_category(self, category_name: str) -> SensitiveCategory:
        normalized = category_name.lower().replace(" ", "_")
        if normalized not in [c.value for c in SensitiveCategory]:
            try:
                new_cat = SensitiveCategory(normalized)
            except ValueError:
                return SensitiveCategory.CUSTOM
            self._categories[new_cat] = []
            return new_cat
        return SensitiveCategory(normalized)

    def remove_category(self, category: SensitiveCategory) -> int:
        removed = 0
        pattern_ids = list(self._categories.get(category, []))
        for pid in pattern_ids:
            self._patterns.pop(pid, None)
            self._compiled_patterns.pop(pid, None)
            removed += 1
        self._categories.pop(category, None)
        self._thresholds.pop(category, None)
        self.logger.info("Removed category %s with %d patterns", category.value, removed)
        return removed

    def add_whitelist(self, text: str, category: Optional[SensitiveCategory] = None,
                      reason: str = "", created_by: str = "system",
                      expires_in_hours: Optional[int] = None) -> WhitelistEntry:
        expires_at = None
        if expires_in_hours:
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        entry = WhitelistEntry(
            text=text.lower().strip(),
            category=category,
            reason=reason,
            created_by=created_by,
            expires_at=expires_at,
        )
        self._whitelist.append(entry)
        return entry

    def remove_whitelist(self, text: str) -> bool:
        normalized = text.lower().strip()
        for i, entry in enumerate(self._whitelist):
            if entry.text == normalized:
                self._whitelist.pop(i)
                return True
        return False

    def list_whitelist(self, category: Optional[SensitiveCategory] = None) -> List[WhitelistEntry]:
        if category:
            return [e for e in self._whitelist if e.category == category or e.category is None]
        return list(self._whitelist)

    def is_whitelisted(self, text: str) -> bool:
        normalized = text.lower().strip()
        now = datetime.utcnow()
        for entry in self._whitelist:
            if not entry.is_active:
                continue
            if entry.expires_at and now > entry.expires_at:
                continue
            if entry.text in normalized or normalized in entry.text:
                return True
        return False

    def add_exemption(self, description: str, category: Optional[SensitiveCategory] = None,
                      pattern_ids: Optional[List[str]] = None,
                      condition: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
                      expires_in_hours: Optional[int] = None) -> ExemptionRule:
        exemption_id = f"exemption_{uuid.uuid4().hex[:12]}"
        expires_at = None
        if expires_in_hours:
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        er = ExemptionRule(
            exemption_id=exemption_id,
            description=description,
            category=category,
            pattern_ids=pattern_ids or [],
            condition=condition,
            expires_at=expires_at,
        )
        self._exemptions[exemption_id] = er
        return er

    def remove_exemption(self, exemption_id: str) -> bool:
        if exemption_id in self._exemptions:
            self._exemptions.pop(exemption_id)
            return True
        return False

    def list_exemptions(self) -> List[ExemptionRule]:
        return list(self._exemptions.values())

    def is_exempted(self, content: str, category: SensitiveCategory,
                    context: Optional[Dict[str, Any]] = None) -> bool:
        now = datetime.utcnow()
        for er in self._exemptions.values():
            if not er.is_active:
                continue
            if er.expires_at and now > er.expires_at:
                continue
            if er.category and er.category != category:
                continue
            if er.condition:
                ctx = context or {}
                if er.condition(content, ctx):
                    return True
            elif er.category == category:
                return True
        return False

    def set_category_threshold(self, category: SensitiveCategory, threshold: float) -> None:
        self._thresholds[category] = max(0.0, min(1.0, threshold))

    def get_category_threshold(self, category: SensitiveCategory) -> float:
        return self._thresholds.get(category, self._default_threshold)

    def set_severity_score(self, level: SensitivityLevel, score: float) -> None:
        self._severity_scores[level] = score

    def get_severity_score(self, level: SensitivityLevel) -> float:
        return self._severity_scores.get(level, 1)

    def detect_language(self, content: str) -> str:
        if not self._language_detection_enabled or not content.strip():
            return "en"
        content_sample = content[:500].strip()
        if not content_sample:
            return "en"
        best_lang = "en"
        best_score = 0
        for lang, lang_re in LANGUAGE_PATTERNS.items():
            matches = len(lang_re.findall(content_sample))
            score = matches / max(len(content_sample.split()), 1)
            if score > best_score:
                best_score = score
                best_lang = lang
        return best_lang

    def extract_context(self, content: str, pos: int, length: int) -> Tuple[str, str]:
        start = max(0, pos - self._context_window)
        end = min(len(content), pos + length + self._context_window)
        before = content[start:pos]
        after = content[pos + length:end]
        return before.strip(), after.strip()

    def compute_sensitivity_score(self, matches: List[SensitiveMatch]) -> float:
        if not matches:
            return 0.0
        total = 0.0
        for m in matches:
            severity_weight = SEVERITY_WEIGHTS.get(m.severity, 0.5)
            weighted = m.confidence * severity_weight * m.score
            total += weighted
        return min(total, float(self._max_score))

    def filter(self, content: str, context: Optional[Dict[str, Any]] = None,
               categories: Optional[List[SensitiveCategory]] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        ctx = context or {}
        language = self.detect_language(content)
        all_matches: List[SensitiveMatch] = []
        target_categories = categories or list(self._categories.keys())
        now = datetime.utcnow()

        for cat in target_categories:
            threshold = self.get_category_threshold(cat)
            if self.is_exempted(content, cat, ctx):
                continue
            pattern_ids = self._categories.get(cat, [])
            for pid in pattern_ids:
                sp = self._patterns.get(pid)
                if not sp or not sp.is_active:
                    continue
                if sp.languages and language not in sp.languages:
                    continue
                compiled = self._compiled_patterns.get(pid)
                if compiled is None:
                    continue
                try:
                    for match in compiled.finditer(content):
                        matched_text = match.group()
                        if self.is_whitelisted(matched_text):
                            continue
                        context_before, context_after = self.extract_context(
                            content, match.start(), match.end() - match.start()
                        )
                        confidence = min(1.0, len(matched_text) / 20.0 + 0.5)
                        severity_weight = SEVERITY_WEIGHTS.get(sp.severity, 0.5)
                        score = severity_weight * sp.weight * 10
                        sm = SensitiveMatch(
                            pattern_id=pid,
                            category=cat,
                            matched_text=matched_text,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            confidence=confidence,
                            severity=sp.severity,
                            score=score,
                            language=language,
                            context_before=context_before,
                            context_after=context_after,
                            strategy=sp.strategy,
                        )
                        all_matches.append(sm)
                except re.error as e:
                    self.logger.warning("Regex error on pattern %s: %s", pid, e)

        if self._enable_context_analysis:
            all_matches = self._apply_context_analysis(all_matches, ctx)

        all_matches.sort(key=lambda m: m.score, reverse=True)
        total_score = self.compute_sensitivity_score(all_matches)

        blocked = total_score >= self._block_threshold
        warned = total_score >= self._warn_threshold and not blocked

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        self._stats.record_evaluation(processing_time_ms, all_matches, blocked=blocked, warned=warned)

        violations = []
        if all_matches:
            for m in all_matches[:20]:
                violation_type = ViolationType.KEYWORD_MATCH
                if m.strategy == MatchStrategy.REGEX:
                    violation_type = ViolationType.REGEX_MATCH
                elif m.strategy == MatchStrategy.SEMANTIC:
                    violation_type = ViolationType.SEMANTIC_VIOLATION
                severity = RuleSeverity.HIGH
                if m.severity == SensitivityLevel.LOW:
                    severity = RuleSeverity.LOW
                elif m.severity == SensitivityLevel.MEDIUM:
                    severity = RuleSeverity.MEDIUM
                elif m.severity == SensitivityLevel.CRITICAL:
                    severity = RuleSeverity.CRITICAL
                action = ActionTaken.WARNING
                if blocked:
                    action = ActionTaken.BLOCK
                elif m.severity == SensitivityLevel.CRITICAL:
                    action = ActionTaken.ESCALATE
                v = Violation(
                    rule_id=f"sensitive_{m.category.value}_{m.pattern_id}",
                    rule_name=f"Sensitive Content - {m.category.value}",
                    rule_tier=RuleTier.SAFETY,
                    rule_severity=severity,
                    violation_type=violation_type,
                    matched_content=m.matched_text,
                    matched_patterns=[m.pattern_id],
                    confidence_score=m.confidence,
                    position_info={"start": m.start_pos, "end": m.end_pos},
                    action_taken=action,
                    blocked=blocked,
                    explanation=f"Sensitive content detected in category '{m.category.value}': {m.matched_text}",
                    detected_at=now,
                )
                violations.append(v)

        result = {
            "clean": not bool(all_matches),
            "blocked": blocked,
            "warned": warned,
            "total_score": round(total_score, 2),
            "total_detections": len(all_matches),
            "language": language,
            "detections": [
                {
                    "category": m.category.value,
                    "matched_text": m.matched_text,
                    "confidence": round(m.confidence, 3),
                    "severity": m.severity.value,
                    "score": round(m.score, 2),
                    "position": {"start": m.start_pos, "end": m.end_pos},
                }
                for m in all_matches[:50]
            ],
            "detection_summary": {
                "categories_found": list(set(m.category.value for m in all_matches)),
                "highest_severity": max((m.severity for m in all_matches), key=lambda s: SEVERITY_WEIGHTS.get(s, 0)).value if all_matches else None,
                "average_confidence": round(sum(m.confidence for m in all_matches) / len(all_matches), 3) if all_matches else 0.0,
            },
            "processing_time_ms": processing_time_ms,
            "filter_id": self.filter_id,
            "version": self._version,
            "violations": violations,
        }
        return result

    def _apply_context_analysis(self, matches: List[SensitiveMatch],
                                 context: Dict[str, Any]) -> List[SensitiveMatch]:
        if not matches:
            return matches
        filtered: List[SensitiveMatch] = []
        for m in matches:
            ctx_lower = (m.context_before + " " + m.context_after).lower()
            if "not " in ctx_lower or "no " in ctx_lower or "without " in ctx_lower:
                boosters = ["is not", "are not", "was not", "were not", "does not",
                            "do not", "did not", "has not", "have not", "had not",
                            "will not", "would not", "could not", "should not",
                            "might not", "must not", "shall not", "cannot"]
                if any(b in ctx_lower for b in boosters):
                    m.confidence *= 0.3
                    m.score *= 0.3
            if "example" in ctx_lower or "for illustration" in ctx_lower or "hypothetical" in ctx_lower:
                m.confidence *= 0.5
                m.score *= 0.5
            if "educational" in ctx_lower or "academic" in ctx_lower or "research" in ctx_lower:
                m.confidence *= 0.6
                m.score *= 0.6
            if m.confidence > 0.1:
                filtered.append(m)
        return filtered

    def get_stats(self) -> Dict[str, Any]:
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        self._stats.reset()
        self.logger.info("Statistics reset for filter %s", self.filter_id)

    def generate_report(self, include_recent: bool = False) -> Dict[str, Any]:
        report = {
            "filter_id": self.filter_id,
            "version": self._version,
            "generated_at": datetime.utcnow().isoformat(),
            "stats": self._stats.to_dict(),
            "configuration": {
                "language_detection": self._language_detection_enabled,
                "default_threshold": self._default_threshold,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "context_window": self._context_window,
                "context_analysis": self._enable_context_analysis,
                "max_score": self._max_score,
            },
            "categories": {
                cat.value: {
                    "pattern_count": len(self._categories.get(cat, [])),
                    "threshold": self.get_category_threshold(cat),
                }
                for cat in self._categories
            },
            "patterns": {
                pid: {
                    "category": sp.category.value,
                    "severity": sp.severity.value,
                    "weight": sp.weight,
                    "active": sp.is_active,
                }
                for pid, sp in self._patterns.items()
            },
            "whitelist_count": len(self._whitelist),
            "exemption_count": len(self._exemptions),
        }
        if include_recent:
            report["recent_detections"] = list(self._stats.recent_detections)
        return report

    def export_config(self) -> Dict[str, Any]:
        return {
            "filter_id": self.filter_id,
            "version": self._version,
            "configuration": {
                "language_detection": self._language_detection_enabled,
                "default_threshold": self._default_threshold,
                "block_threshold": self._block_threshold,
                "warn_threshold": self._warn_threshold,
                "context_window": self._context_window,
                "context_analysis": self._enable_context_analysis,
                "max_score": self._max_score,
                "severity_scores": {k.value: v for k, v in self._severity_scores.items()},
                "thresholds": {k.value: v for k, v in self._thresholds.items()},
            },
            "patterns": [
                {
                    "pattern_id": sp.pattern_id,
                    "category": sp.category.value,
                    "pattern": sp.pattern,
                    "strategy": sp.strategy.value,
                    "severity": sp.severity.value,
                    "weight": sp.weight,
                    "description": sp.description,
                    "languages": sp.languages,
                    "is_active": sp.is_active,
                }
                for sp in self._patterns.values()
            ],
            "whitelist": [
                {
                    "text": e.text,
                    "category": e.category.value if e.category else None,
                    "reason": e.reason,
                    "created_by": e.created_by,
                    "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                }
                for e in self._whitelist
            ],
        }

    def import_config(self, config: Dict[str, Any]) -> int:
        imported = 0
        if "configuration" in config:
            cfg = config["configuration"]
            self._language_detection_enabled = cfg.get("language_detection", self._language_detection_enabled)
            self._default_threshold = cfg.get("default_threshold", self._default_threshold)
            self._block_threshold = cfg.get("block_threshold", self._block_threshold)
            self._warn_threshold = cfg.get("warn_threshold", self._warn_threshold)
            self._context_window = cfg.get("context_window", self._context_window)
            self._enable_context_analysis = cfg.get("context_analysis", self._enable_context_analysis)
            self._max_score = cfg.get("max_score", self._max_score)
            if "severity_scores" in cfg:
                for k, v in cfg["severity_scores"].items():
                    try:
                        self._severity_scores[SensitivityLevel(k)] = v
                    except ValueError:
                        pass
            if "thresholds" in cfg:
                for k, v in cfg["thresholds"].items():
                    try:
                        self._thresholds[SensitiveCategory(k)] = v
                    except ValueError:
                        pass
        if "patterns" in config:
            for p in config["patterns"]:
                try:
                    cat = SensitiveCategory(p["category"])
                except ValueError:
                    cat = SensitiveCategory.CUSTOM
                try:
                    strategy = MatchStrategy(p.get("strategy", "regex"))
                except ValueError:
                    strategy = MatchStrategy.REGEX
                try:
                    severity = SensitivityLevel(p.get("severity", "medium"))
                except ValueError:
                    severity = SensitivityLevel.MEDIUM
                self.add_pattern(
                    category=cat,
                    pattern=p["pattern"],
                    strategy=strategy,
                    severity=severity,
                    weight=p.get("weight", 1.0),
                    description=p.get("description", ""),
                    languages=p.get("languages"),
                )
                imported += 1
        if "whitelist" in config:
            for e in config["whitelist"]:
                cat = None
                if e.get("category"):
                    try:
                        cat = SensitiveCategory(e["category"])
                    except ValueError:
                        pass
                self.add_whitelist(
                    text=e["text"],
                    category=cat,
                    reason=e.get("reason", ""),
                    created_by=e.get("created_by", "import"),
                )
        self.logger.info("Imported %d patterns from config", imported)
        return imported

    def to_validation_result(self, filter_result: Dict[str, Any]) -> ValidationResult:
        violations = filter_result.get("violations", [])
        return ValidationResult(
            valid=filter_result.get("clean", True),
            total_score=1.0 - min(1.0, filter_result.get("total_score", 0) / self._max_score),
            confidence=1.0 - (len(violations) / max(len(violations) + 1, 1)),
            total_rules_evaluated=len(self._patterns),
            rules_triggered=len(violations),
            rules_violated=len(violations),
            violations=violations,
            critical_violations=[v for v in violations if v.is_critical()],
            warnings=[v for v in violations if v.action_taken == ActionTaken.WARNING],
            processing_time_ms=filter_result.get("processing_time_ms", 0),
            evaluator_version=self._version,
        )
