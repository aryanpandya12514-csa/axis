import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pymongo

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    logger.info("Initializing SentenceTransformer: 'all-MiniLM-L6-v2'")
    model = SentenceTransformer('all-MiniLM-L6-v2')
except ImportError:
    logger.warning("sentence-transformers not installed. Embedding features will be mocked.")
    model = None

def get_text_embedding(text: str) -> List[float]:
    """Generates a dense normalized vector embedding."""
    if model is None:
        return [0.0] * 384
    return model.encode(text, normalize_embeddings=True).tolist()

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the great-circle distance between two earth points in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_cosine_distance(vec1: List[float], vec2: List[float]) -> float:
    """Calculates standard cosine distance for normalized vectors."""
    if len(vec1) != len(vec2) or len(vec1) == 0:
        return 1.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    return max(0.0, 1.0 - dot_product)

# --- MongoDB Admin Dashboard Infrastructure ---

def ingest_complaint(complaint: Dict[str, Any], db_collection: pymongo.collection.Collection) -> str:
    """
    Ingests a newly submitted raw complaint matrix. Automatically analyzes existing
    database incidents via purely physical/semantic clustering variables and assigns Group IDs statically.
    Returns the final assigned group_id natively injected into MongoDB.
    """
    complaint_id = complaint["ctoken"]
    category = complaint["department"]
    
    # 0,0 gps fail-safe logic ensuring broken coords do not cluster
    lat = complaint["location"]["lat"]
    lng = complaint["location"]["lng"]
    if lat == 0.0 and lng == 0.0:
        logger.warning(f"GPS bypassed for '{complaint_id}'. Enforcing novel parent status.")
        complaint["is_master"] = True
        complaint["group_id"] = complaint_id
        db_collection.insert_one(complaint)
        return complaint_id

    # Filter purely for same-category metrics within 14 days timeframe directly in MongoDB
    date_threshold = datetime.utcnow() - timedelta(days=14)
    candidates = list(db_collection.find({
        "department": category,
        "created_at": {"$gte": date_threshold}
    }))
    
    best_group_id = None
    best_distance = float('inf')
    
    embedding = complaint.get("embedding")
    if not embedding:
        embedding = get_text_embedding(complaint["text"])
        complaint["embedding"] = embedding
        
    for doc in candidates:
        m_lat = doc["location"].get("lat", 0.0)
        m_lng = doc["location"].get("lng", 0.0)
        
        # Spatial constraint bounding (Maximum 300m range)
        spatial_dist = calculate_haversine_distance(lat, lng, m_lat, m_lng)
        if spatial_dist > 300:
            continue
            
        # Standardize vector logic ensuring cosine bounds limit checks out
        vec_dist = calculate_cosine_distance(embedding, doc.get("embedding", []))
        if vec_dist < 0.22 and vec_dist < best_distance:
            best_distance = vec_dist
            best_group_id = doc["group_id"]
            
    if best_group_id:
        complaint["is_master"] = False
        complaint["group_id"] = best_group_id
        logger.info(f"Routed duplicate clone '{complaint_id}' mapping into Group '{best_group_id}'")
    else:
        complaint["is_master"] = True
        complaint["group_id"] = complaint_id
        logger.info(f"Routed novel incident '{complaint_id}' establishing independent Master record.")

    db_collection.insert_one(complaint)
    return complaint["group_id"]


def get_dashboard_clusters(db_collection: pymongo.collection.Collection) -> List[Dict[str, Any]]:
    """
    Pipeline retrieving exclusively master issues coupled natively with counting aggregate arrays
    of all identically clustered child-issue subnodes assigned matching group_ids.
    """
    pipeline = [
        # Only fetch primary distinct mapped incidents
        {"$match": {"is_master": True}},
        # Lookup joining grouped identical incidents recursively inside array mappings explicitly
        {"$lookup": {
            "from": db_collection.name,
            "localField": "group_id",
            "foreignField": "group_id",
            "as": "merged_complaints"
        }},
        # Expose natively aggregate count formatting dropping memory bloat
        {"$addFields": {
            "merged_complaint_count": {"$size": "$merged_complaints"}
        }},
        # Cull heavy embedded mapping variables for clean API payload return explicitly
        {"$project": {
            "merged_complaints": 0,
            "embedding": 0
        }}
    ]
    return list(db_collection.aggregate(pipeline))


def update_cluster_status(group_id: str, new_status: str, db_collection: pymongo.collection.Collection) -> int:
    """
    Executes an atomic synchronized metadata state update explicitly trickling directly down
    to natively update identical cloned siblings simultaneously enforcing synchronous state handling.
    Returns count of updated records.
    """
    valid_statuses = {"pending", "in progress", "resolved"}
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Expected one of {valid_statuses}")
        
    result = db_collection.update_many(
        {"group_id": group_id},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    )
    logger.info(f"Pushed state update '{new_status}' synchronizing across {result.modified_count} related records for Group {group_id}")
    return result.modified_count


if __name__ == "__main__":
    import uuid
    import json
    
    print("====== Running MongoDB Deduplication Admin Tests ======\n")
    client = pymongo.MongoClient('mongodb://localhost:27017/')
    db = client['citysync_testing']
    test_collection = db['test_complaints']
    test_collection.delete_many({}) # Clear testing layer
    
    def mock_complaint(text, lat, lng, dept):
        return {
            "ctoken": str(uuid.uuid4()),
            "subject": f"Issue in {dept}",
            "text": text,
            "location": {"lat": lat, "lng": lng},
            "status": "pending",
            "department": dept,
            "created_at": datetime.utcnow()
        }

    # Generate isolated baseline report natively
    m_1 = mock_complaint("Fallen tree branch on car", 21.0, 79.0, "Garden Department")
    c1_grouping = ingest_complaint(m_1, test_collection)
    
    # Generate spatially and semantically identical record
    m_2 = mock_complaint("A huge tree crashed into vehicles nearby", 21.0001, 79.0001, "Garden Department") # Very close
    c2_grouping = ingest_complaint(m_2, test_collection)
    
    # Generate irrelevant novel complaint securely ensuring mapping rejection
    m_3 = mock_complaint("Pothole outside market gate limits passing vehicles", 21.1, 79.1, "PWD") 
    c3_grouping = ingest_complaint(m_3, test_collection)

    print("\n--- Dashboard Clusters ---")
    dash = get_dashboard_clusters(test_collection)
    for res in dash:
        res["_id"] = str(res["_id"]) # Strip ObjectId for console printing securely
    print(json.dumps(dash, indent=2))
    
    print("\n--- Synchronizing Dashboard Status Propagation ---")
    update_cluster_status(c1_grouping, "resolved", test_collection)
    updated_records_query = list(test_collection.find({"group_id": c1_grouping}))
    
    for updated in updated_records_query:
        print(f"Record {updated['ctoken']} (Master: {updated['is_master']}) -> STATUS: {updated['status']}")
