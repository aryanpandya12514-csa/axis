import logging
from typing import Dict, Any
from datetime import datetime, timedelta

try:
    import psycopg2
    from psycopg2.extensions import connection as PgConnection
except ImportError:
    PgConnection = Any

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DEPARTMENTS = {
    "PWD - Public Works Department": {
        "email": "pwd@nmcnagpur.gov.in",
        "phone": "0712-2567011",
        "officers": {"default": "A. K. Sharma (Executive Engineer)"}
    },
    "Electrical Department": {
        "email": "electrical@nmcnagpur.gov.in",
        "phone": "0712-2567012",
        "officers": {"default": "S. V. Patil (Superintending Engineer)"}
    },
    "Solid Waste Management": {
        "email": "swm@nmcnagpur.gov.in",
        "phone": "0712-2567013",
        "officers": {"default": "Dr. R. Mishra (Nodal Officer)"}
    },
    "NMC Water Supply Department": {
        "email": "water@nmcnagpur.gov.in",
        "phone": "0712-2567014",
        "officers": {"default": "V. D. Gupta (Chief Engineer)"}
    },
    "Drainage Department": {
        "email": "drainage@nmcnagpur.gov.in",
        "phone": "0712-2567015",
        "officers": {"default": "P. N. Deshmukh (Executive Engineer)"}
    },
    "Encroachment Removal Cell": {
        "email": "encroachment@nmcnagpur.gov.in",
        "phone": "0712-2567016",
        "officers": {"default": "M. R. Kamble (Assistant Commissioner)"}
    },
    "Environment Department": {
        "email": "environment@nmcnagpur.gov.in",
        "phone": "0712-2567017",
        "officers": {"default": "Dr. S. K. Joshi (Environmental Officer)"}
    },
    "Animal Husbandry Department": {
        "email": "animal@nmcnagpur.gov.in",
        "phone": "0712-2567018",
        "officers": {"default": "Dr. G. V. Wagh (Veterinary Officer)"}
    },
    "Garden Department": {
        "email": "garden@nmcnagpur.gov.in",
        "phone": "0712-2567019",
        "officers": {"default": "N. S. Rathod (Garden Superintendent)"}
    },
    "Building & Structural Department": {
        "email": "building@nmcnagpur.gov.in",
        "phone": "0712-2567020",
        "officers": {"default": "R. M. Kulkarni (Town Planner)"}
    },
    "General Grievance Cell": {
        "email": "grievance@nmcnagpur.gov.in",
        "phone": "0712-2567021",
        "officers": {"default": "T. L. Bhoyar (PRO)"}
    }
}


def get_department_contact(department_name: str, ward_id: int) -> Dict[str, str]:
    """
    Returns contact info and the designated officer for a given department and ward.
    Uses fallback 'default' mapping if a specific ward officer isn't mapped.
    """
    dept_info = DEPARTMENTS.get(department_name, DEPARTMENTS["General Grievance Cell"])
    
    officer = dept_info["officers"].get(str(ward_id))
    if not officer:
        officer = dept_info["officers"]["default"]
        if ward_id > 0:
             officer += f" - Ward {ward_id}"
             
    return {
        "dept_name": department_name,
        "dept_email": dept_info["email"],
        "dept_phone": dept_info["phone"],
        "officer_name": officer
    }


def route_complaint(
    complaint_id: str, 
    classifier_output: Dict[str, Any], 
    priority_score_result: Dict[str, Any], 
    ward_id: int,
    db_conn: PgConnection
) -> Dict[str, Any]:
    """
    Updates the Postgres database to assign the complaint to the correct department
    and calculates the estimated resolution time based on priority score SLAs.
    Inserts an event into the complaint timeline.

    Args:
        complaint_id (str): UUID or string ID of the database row.
        classifier_output (dict): The result output directly from CitySync NLP classifier.
        priority_score_result (dict): The result from priority_scorer.py.
        ward_id (int): Dynamic ward parameter parsed from caller script.
        db_conn: The active psycopg2 database connection.

    Returns:
        dict: Routing confirmation and dispatch details.
    """
    final_result = classifier_output.get("final_result", {})
    department = final_result.get("department", "General Grievance Cell")
    severity = final_result.get("severity", 0)
    
    # Adopt unified hours-based SLA injected by the priority_scorer module
    now = datetime.now()
    eta_hours = priority_score_result.get("recommended_sla_hours", 336)
    priority_label = priority_score_result.get("priority_label", "LOW")
    estimated_resolution = now + timedelta(hours=eta_hours)
    
    contact_info = get_department_contact(department, ward_id)
    
    try:
        with db_conn.cursor() as cursor:
            # 1. Update the main complaint row
            update_sql = """
                UPDATE complaints
                SET dept_name = %s,
                    status = 'routed',
                    routed_at = %s,
                    estimated_resolution = %s
                WHERE id = %s
            """
            cursor.execute(update_sql, (department, now, estimated_resolution, complaint_id))
            
            # 2. Insert into the timeline table for auditing and tracking
            timeline_sql = """
                INSERT INTO complaint_timeline (complaint_id, event_type, description, created_at)
                VALUES (%s, %s, %s, %s)
            """
            event_desc = f"Complaint automatically routed to {department} (Severity: {priority_label}). ETA: {eta_hours} hours."
            cursor.execute(timeline_sql, (complaint_id, "SYSTEM_ROUTED", event_desc, now))
            
        db_conn.commit()
        logger.info(f"Successfully routed complaint {complaint_id} to {department}")
        
    except Exception as e:
        db_conn.rollback()
        logger.error(f"Database error during routing: {e}")
        return {"error": str(e), "status": "failed"}

    dispatch_message = final_result.get("routing_reason", "No reason provided")

    return {
        "complaint_id": complaint_id,
        "department": department,
        "contact_info": contact_info,
        "estimated_resolution": estimated_resolution.isoformat(),
        "status": "routed",
        "routing_reason": dispatch_message
    }


def send_dept_notification(routing_result: dict) -> bool:
    """
    Simulates sending an email or SMS notification to the department officer.
    """
    contact = routing_result.get("contact_info", {})
    if not contact:
        return False
        
    logger.info(f"\n--- DISPATCHING NOTIFICATION ---")
    logger.info(f"TO: {contact.get('officer_name')} <{contact.get('dept_email')}>")
    logger.info(f"SUBJECT: URGENT: New Complaint Assigned - {routing_result.get('complaint_id')}")
    logger.info(f"DEADLINE: {routing_result.get('estimated_resolution')}")
    logger.info(f"REASON: {routing_result.get('routing_reason')}")
    logger.info(f"--------------------------------\n")
    
    return True


if __name__ == "__main__":
    print("====== Running Router Tests ======\n")
    
    class MockCursor:
        def execute(self, sql, params=None):
            logger.debug(f"Mock executed SQL. Params: {params}")
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class MockConnection:
        def cursor(self): return MockCursor()
        def commit(self): logger.debug("Mock commit")
        def rollback(self): logger.debug("Mock rollback")
        
    mock_db = MockConnection()
    
    mock_classifier_output = {
        "final_result": {
            "department": "PWD - Public Works Department",
            "severity": 1,
            "routing_reason": "Potholes fall under the jurisdiction of the Public Works Department."
        }
    }
    
    mock_priority_score_result = {
        "recommended_sla_hours": 72,
        "priority_label": "MEDIUM"
    }
    
    test_cmp_id = "test-uuid-1234"
    print(f"Routing simulated complaint: {test_cmp_id}...")
    
    route_data = route_complaint(
        complaint_id=test_cmp_id, 
        classifier_output=mock_classifier_output, 
        priority_score_result=mock_priority_score_result,
        ward_id=15,
        db_conn=mock_db
    )
    
    print("\n[Return Data]")
    import json
    print(json.dumps(route_data, indent=2))
    
    print("\n[Notification]")
    send_dept_notification(route_data)
