import logging
from enum import Enum, IntEnum
from typing import Dict, Any, TypedDict

try:
    import psycopg2
    from psycopg2.extensions import connection as PgConnection
except ImportError:
    # Fallback type if psycopg2 is missing
    PgConnection = Any

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Enums & TypedDicts for Safety ---

class PriorityLabel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class SLAHours(IntEnum):
    CRITICAL = 4
    HIGH = 24
    MEDIUM = 72
    LOW = 336

class GeminiResult(TypedDict, total=False):
    severity: int
    needs_immediate_action: bool
    # other fields from classifier can exist here

class ScoreBreakdown(TypedDict):
    base_severity_score: int
    frequency_score: int
    vulnerability_score: int
    time_decay_bonus: int
    immediate_action_bonus: int

class PriorityResult(TypedDict):
    priority_score: int
    priority_label: PriorityLabel
    recommended_sla_hours: SLAHours
    score_breakdown: ScoreBreakdown

# Hardcoded dict of 38 Nagpur wards with vulnerability scores from 0-10
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
    """
    Returns the hardcoded vulnerability score (0-10) for a given Nagpur ward.
    Defaults to 0 if the ward is unknown.
    """
    return WARD_VULNERABILITY.get(ward_id, 0)

def get_duplicate_count(category: str, lat: float, lng: float, db_conn: PgConnection) -> int:
    """
    Queries PostGIS to count the number of identical complaint categories
    within a 300m radius over the last 14 days.
    
    Optimized: Limits counting at 4 rows since priority maxes out at 4 duplicates.
    Optimized: Removed location::geography cast to allow spatial GIST indexes to be used natively.
    """
    # Guard against default/empty coordinates
    if not lat or not lng or (lat == 0 and lng == 0):
        return 0

    query = """
        SELECT count(*) FROM (
            SELECT 1
            FROM complaints
            WHERE category = %s
              AND created_at >= NOW() - INTERVAL '14 days'
              AND ST_DWithin(
                    location,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    300
                  )
            LIMIT 4
        ) as subquery
    """
    try:
        with db_conn.cursor() as cursor:
            # PostGIS MakePoint signature is (longitude, latitude)
            cursor.execute(query, (category, lng, lat))  
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"PostGIS query failed: {e}")
        return 0

def calculate_priority_score(
    gemini_result: GeminiResult,
    duplicate_count: int,
    ward_vulnerability: int,
    hours_since_submission: int
) -> PriorityResult:
    """
    Calculates the priority score (0-100) based on multiple physical 
    and temporal factors from the incident.
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


if __name__ == "__main__":
    import json
    print("====== Running Optimized Priority Scorer Tests ======\n")
    
    class MockCursor:
        def __init__(self, mock_count):
            self.mock_count = mock_count
        def execute(self, sql, params=None):
            logger.debug(f"Mock executed PostGIS LIMIT 4 query: params={params}")
        def fetchone(self):
            return (self.mock_count,)
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class MockConnection:
        def __init__(self, count):
            self.count = min(count, 4) # Represents database capping at LIMIT 4
        def cursor(self):
            return MockCursor(self.count)
            
    # Mock Dictionary Cast to TypedDict matches
    gemini_high: GeminiResult = {"severity": 2, "needs_immediate_action": True}
    gemini_medium: GeminiResult = {"severity": 1, "needs_immediate_action": False}
    gemini_low: GeminiResult = {"severity": 0, "needs_immediate_action": False}
    
    test_cases = [
        {
            "name": "Test 1: Critical Emergency (High severity, vulnerable ward, highly reported > 4 dupes maxes out, fresh report)",
            "gemini_result": gemini_high,
            "ward_id": 15,            # Vulnerability = 10
            "db_mock_count": 50,      # 50 duplicates in DB (Simulates DB limiting to 4)
            "hours_since": 1          # 1 hr ago (Decay = 9)
        },
        {
            "name": "Test 2: Medium Spilling Garbage (Medium severity, average ward, no duplicates, older report)",
            "gemini_result": gemini_medium,
            "ward_id": 7,             # Vulnerability = 5
            "db_mock_count": 0,       # 0 duplicates
            "hours_since": 12         # 12 hrs ago (Decay = 0)
        },
        {
            "name": "Test 3: Nuisance / Stray Animal (Low severity, low vulnerability ward, freshly reported)",
            "gemini_result": gemini_low,
            "ward_id": 9,             # Vulnerability = 1
            "db_mock_count": 1,       # 1 duplicate
            "hours_since": 2          # 2 hrs ago (Decay = 8)
        },
        {
            "name": "Test 4: Clock Skew Defense Test (Negative time passed)",
            "gemini_result": gemini_low,
            "ward_id": 9,
            "db_mock_count": 0,
            "hours_since": -5         # Server clock issues (-5 hours) should clamp to 0 yielding decay of 10
        }
    ]
    
    for tc in test_cases:
        print(f"--- {tc['name']} ---")
        vuln = get_ward_vulnerability(tc["ward_id"])
        db_mock = MockConnection(count=tc["db_mock_count"])
        dupes = get_duplicate_count("mock_category", 21.1458, 79.0882, db_mock)
        
        result = calculate_priority_score(
            gemini_result=tc["gemini_result"],
            duplicate_count=dupes,
            ward_vulnerability=vuln,
            hours_since_submission=tc["hours_since"]
        )
        
        # Make Enums JSON serializable for printing
        printable_result = {
            **result,
            "priority_label": result["priority_label"].value,
            "recommended_sla_hours": result["recommended_sla_hours"].value
        }
        print(json.dumps(printable_result, indent=2))
        print("\n" + "="*50 + "\n")
