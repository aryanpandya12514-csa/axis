import logging
from enum import Enum, IntEnum
from typing import Dict, Any, TypedDict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class PriorityLabel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# SLA = Service Level Agreement - matlab kitne time me complaint solve honi chahiye

class SLAHours(IntEnum):
    CRITICAL = 4
    HIGH = 24
    MEDIUM = 72
    LOW = 336

class GeminiResult(TypedDict, total=False):  
    severity: int
    needs_immediate_action: bool


# ScoreBreakdown -Defines structure for explaining score components.
class ScoreBreakdown(TypedDict):

    base_severity_score: int
    frequency_score: int
    vulnerability_score: int
    time_decay_bonus: int
    immediate_action_bonus: int

# PriorityResult - Final output structure
class PriorityResult(TypedDict):
    priority_score: int
    priority_label: PriorityLabel
    recommended_sla_hours: SLAHours
    score_breakdown: ScoreBreakdown

WARD_VULNERABILITY: Dict[int, int] = {
    1: 4,  2: 6,  3: 2,  4: 8,  5: 3,
    6: 9,  7: 5,  8: 7,  9: 1,  10: 5,
    11: 8, 12: 4, 13: 9, 14: 2, 15: 10,
    16: 3, 17: 6, 18: 1, 19: 5, 20: 7,
    21: 5, 22: 5, 23: 5, 24: 5, 25: 5,
    26: 5, 27: 5, 28: 5, 29: 5, 30: 5,
    31: 5, 32: 5, 33: 5, 34: 5, 35: 5,
    36: 5, 37: 5, 38: 5
}

def get_ward_vulnerability(ward_id: int) -> int:
    """Returns the hardcoded vulnerability score (0-10) for a given Nagpur ward."""
    return WARD_VULNERABILITY.get(ward_id, 0)

def calculate_priority_score(
    gemini_result: Dict[str, Any],
    duplicate_count: int,
    ward_vulnerability: int,
    hours_since_submission: int
) -> PriorityResult:
    """
    Calculates the priority score (0-100) purely in memory based on variables 
    passed downstream by the host Flask application.
    """
    severity = gemini_result.get("severity", 0)
    needs_immediate = gemini_result.get("needs_immediate_action", False)
    
    # 1. Base Score
    base = max(0, severity * 30)
    
    # 2. Duplicate Density Bonus (Capped at 20 points, reached at 4 duplicates)
    frequency = min(duplicate_count * 5, 20)
    
    # 3. Ward Vulnerability 
    vuln = max(0, ward_vulnerability * 2)
    
    # 4. Temporal Decay (Defend against negative hours from clock skew)
    safe_hours = max(0, hours_since_submission)
    decay = max(0, 10 - safe_hours)
    
    # 5. Immediate Action Override Flag
    immediate = 10 if needs_immediate else 0
    
    total_score = min(base + frequency + vuln + decay + immediate, 100)
    
    # SLA Determination
    if total_score >= 80:
        label = PriorityLabel.CRITICAL
        sla = SLAHours.CRITICAL
    elif total_score >= 60:
        label = PriorityLabel.HIGH
        sla = SLAHours.HIGH
    elif total_score >= 40:
        label = PriorityLabel.MEDIUM
        sla = SLAHours.MEDIUM
    else:
        label = PriorityLabel.LOW
        sla = SLAHours.LOW
        
    return {
        "priority_score": total_score,
        "priority_label": label,
        "recommended_sla_hours": sla,
        "score_breakdown": {
            "base_severity_score": base,
            "frequency_score": frequency,
            "vulnerability_score": vuln,
            "time_decay_bonus": decay,
            "immediate_action_bonus": immediate
        }
    }
