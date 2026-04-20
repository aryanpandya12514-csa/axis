import logging
from typing import Dict, Any
from datetime import datetime, timedelta

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
    ward_id: int
) -> Dict[str, Any]:
    """
    Computes department endpoints, calculating SLA ETA purely in-memory.
    Returns structurally complete JSON payload that Flask will push to MongoDB natively.
    """
    final_result = classifier_output.get("final_result", {})
    department = final_result.get("department", "General Grievance Cell")
    
    now = datetime.now()
    eta_hours = priority_score_result.get("recommended_sla_hours", 336)
    estimated_resolution = now + timedelta(hours=eta_hours)
    
    contact_info = get_department_contact(department, ward_id)
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
