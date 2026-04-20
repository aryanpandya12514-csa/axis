import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

import classifier
import dedup_engine
import priority_scorer
import router

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class UnifiedPipeline:
    def __init__(self):
        pass
        
    def _validate_coords(self, lat: float, lng: float):
        if lat == 0.0 and lng == 0.0:
            logger.warning("Zero-coordinates (0,0) detected. Impaired spatial grouping.")
            return False
        return True

    def process_incident(
        self, 
        text: str, 
        image_path: Optional[str], 
        lat: float, 
        lng: float, 
        ward_id: int, 
        active_masters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Master Pipeline - Pure Decoupled Brain mapped directly from Flask router wrapper.
        Executes isolated evaluation models entirely in-memory using arrays fetched natively by PyMongo API hook.
        """
        complaint_id = str(uuid.uuid4())
        logger.info(f"=== Beginning Intake for Complaint {complaint_id} ===")
        
        valid_gps = self._validate_coords(lat, lng)
        
        # 1. Classification
        logger.info("Executing Multimodal Classification Check...")
        class_res = classifier.classify_complaint(text, image_path)
        final_class = class_res.get("final_result", {})
        category = final_class.get("department", "General Grievance Cell")
        
        # 2. Deduplication using Python logic natively mapped over Flask's DB query
        logger.info("Executing Semantic Spatial Deduplication...")
        safe_lat = lat if valid_gps else 0.0
        safe_lng = lng if valid_gps else 0.0
        
        group_id, is_duplicate, duplicate_count, embedding = dedup_engine.assign_or_create_group(
            complaint_id=complaint_id,
            text=text,
            lat=safe_lat,
            lng=safe_lng,
            category=category,
            active_masters=active_masters
        )
        
        # 3. Priority Scoring (Using natively resolved integer from mapped clustering evaluation)
        logger.info("Computing Composite SLA Priority Score...")
        vuln = priority_scorer.get_ward_vulnerability(ward_id)
        
        priority_res = priority_scorer.calculate_priority_score(
            gemini_result=final_class,
            duplicate_count=duplicate_count,
            ward_vulnerability=vuln,
            hours_since_submission=0 # Constant evaluation constraint for fresh intake
        )
        
        try:
             priority_res["priority_label"] = priority_res["priority_label"].value
             priority_res["recommended_sla_hours"] = priority_res["recommended_sla_hours"].value
        except AttributeError:
             pass
        
        # 4. Department Routing Parameters
        logger.info("Resolving Departmental Constraints & Applying SLA Deadlines...")
        route_res = router.route_complaint(
            complaint_id=complaint_id,
            classifier_output=class_res,
            priority_score_result=priority_res,
            ward_id=ward_id
        )
        
        # 5. Officer Dispatch Notification
        logger.info("Dispatching Department Alerts...")
        router.send_dept_notification(route_res)
        
        dup_res = {
            "group_id": group_id,
            "is_duplicate": is_duplicate,
            "cluster_size": duplicate_count,
            "embedding": embedding
        }
        
        summary = class_res.get("final_result", {}).get("summary", "No summary captured.")
        
        return {
            "complaint_id": complaint_id,
            "processed_at": datetime.now().isoformat(),
            "summary": summary,
            "classification": class_res,
            "grouping": dup_res,
            "priority": priority_res,
            "routing": route_res
        }
