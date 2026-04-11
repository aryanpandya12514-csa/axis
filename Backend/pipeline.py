import logging
import uuid
import json
from datetime import datetime
from typing import Dict, Any, Optional

import classifier
import dedup_engine
import priority_scorer
import router

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class UnifiedPipeline:
    def __init__(self):
        # Neural models load instantly via imports (SentenceTransformer and GenerativeModel).
        # We manage the orchestration here.
        pass
        
    def _validate_coords(self, lat: float, lng: float):
        # Edge Case Defense: Bypassed/Corrupt GPS data parsing zero Island.
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
        user_mock_db=None
    ) -> Dict[str, Any]:
        """
        Master Pipeline. Encompasses atomic validation, NLP classification, 
        Semantic+Spatial deduplication, multidimensional scoring, and SLA-aware routing.
        """
        complaint_id = str(uuid.uuid4())
        logger.info(f"=== Beginning Intake for Complaint {complaint_id} ===")
        
        valid_gps = self._validate_coords(lat, lng)
        
        # 1. Classification (Handles fake/missing image natively by shifting 100% weight to text)
        logger.info("Executing Multimodal Classification Check...")
        class_res = classifier.classify_complaint(text, image_path)
        final_class = class_res.get("final_result", {})
        category = final_class.get("category", "General")
        
        # 2. Deduplication 
        logger.info("Executing Semantic Spatial Deduplication...")
        # If coords are dead, we coerce 0.0 into the dedup_engine's fast-path abort
        safe_lat = lat if valid_gps else 0.0
        safe_lng = lng if valid_gps else 0.0
        
        # Format dictionary required natively by our MongoDB admin engine
        complaint_doc = {
            "ctoken": complaint_id,
            "department": category,
            "text": text,
            "location": {"lat": safe_lat, "lng": safe_lng}
        }
        
        # Ingest to MongoDB clustering algorithm (using collection mapping hook)
        group_id = dedup_engine.ingest_complaint(
            complaint_doc, 
            db_collection=user_mock_db.collection
        )
        
        # Re-build legacy mapping to prevent downstream breakage in dummy test
        is_duplicate = group_id != complaint_id
        dup_res = {"group_id": group_id, "is_duplicate": is_duplicate}
        
        duplicate_count = 2 if is_duplicate else 0
        
        # 3. Priority Scoring
        logger.info("Computing Composite SLA Priority Score...")
        vuln = priority_scorer.get_ward_vulnerability(ward_id)
        
        priority_res = priority_scorer.calculate_priority_score(
            gemini_result=final_class,
            duplicate_count=duplicate_count,
            ward_vulnerability=vuln,
            hours_since_submission=0 # Fresh report always has 0 hour decay
        )
        
        # Resolve Python Enum outputs back to primitive formats for JSON dict insertion
        try:
             priority_res["priority_label"] = priority_res["priority_label"].value
             priority_res["recommended_sla_hours"] = priority_res["recommended_sla_hours"].value
        except AttributeError:
             pass
        
        # 4. Department Routing
        logger.info("Resolving Departmental Constraints & Applying SLA Deadlines...")
        route_res = router.route_complaint(
            complaint_id=complaint_id,
            classifier_output=class_res,
            priority_score_result=priority_res,
            ward_id=ward_id,
            db_conn=user_mock_db
        )
        
        # 5. Officer Dispatch Notification
        logger.info("Dispatching Department Alerts...")
        router.send_dept_notification(route_res)
        
        return {
            "complaint_id": complaint_id,
            "processed_at": datetime.now().isoformat(),
            "classification": class_res,
            "grouping": dup_res,
            "priority": priority_res,
            "routing": route_res
        }

if __name__ == "__main__":
    # --- Mock Database Infrastructure ---
    class MockCursor:
        def execute(self, sql, params=None): pass
        def fetchone(self): return None
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class MockCollection:
        def insert_one(self, doc): pass
        def find(self, query): return []

    class MockConnection:
        def cursor(self): return MockCursor()
        def commit(self): pass
        def rollback(self): pass
        def __init__(self):
            self.collection = MockCollection()
        
    db = MockConnection()
    pipeline = UnifiedPipeline()
    
    print("\n" + "="*70)
    print(" PIPELINE EDGE CASE TEST: Fake Image + GPS Signal Loss (0,0)")
    print("="*70)
    
    # Text complains about structural/safety, fake image simulates upload loss, fake coordinates
    response = pipeline.process_incident(
        text="Very huge branch fell on the main electrical wire in Wardha road.",
        image_path="corrupted_upload_123.jpg", 
        lat=0.0, lng=0.0,
        ward_id=6, # High vulnerability (Score 9)
        user_mock_db=db
    )
    
    print("\n" + "="*70)
    print(" FINAL UNIFIED JSON PAYLOAD")
    print("="*70)
    print(json.dumps(response, indent=2))
