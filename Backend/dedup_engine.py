# for semantic similarity and spatial deduplication
import logging
import math
from typing import List, Dict, Any, Tuple

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


def assign_or_create_group(
    complaint_id: str, 
    text: str, 
    lat: float, 
    lng: float, 
    category: str, 
    active_masters: List[Dict[str, Any]]
) -> Tuple[str, bool, int, List[float]]:
    """
    Pure Python decoupled deduplication brain. 
    Analyses incoming payload against a memory array of existing master nodes fetched by Flask.
    Returns: (group_id, is_duplicate, reported_count, embedding)
    """
    embedding = get_text_embedding(text)
    
    # 0,0 GPS fail-safe bypass ensuring broken coords do not cluster globally
    if lat == 0.0 and lng == 0.0:
        logger.warning(f"GPS bypassed for '{complaint_id}'. Enforcing novel parent status.")
        return complaint_id, False, 1, embedding

    best_group_id = None
    best_distance = float('inf')
    best_duplicate_count = 1
    
    for master in active_masters:
        # Cross-validate department constraints first
        if master.get("department") != category:
            continue
            
        m_location = master.get("location", {})
        m_lat = m_location.get("lat", 0.0)
        m_lng = m_location.get("lng", 0.0)
        
        # Spatial constraint bounding (Maximum 300m range)
        spatial_dist = calculate_haversine_distance(lat, lng, float(m_lat), float(m_lng))
        if spatial_dist > 300:
            continue
            
        # Semantic vector grouping validation ensuring strict conceptual linkage
        m_embedding = master.get("embedding", [])
        if not m_embedding: # Handle DB items seamlessly lacking vectors currently
            m_embedding = [0.0]*384


         # semantic similarity ko claculate karenge   
        vec_dist = calculate_cosine_distance(embedding, m_embedding)
        

            # Since vectors are normalized:
            # cosine similarity ≈ dot product
            # distance = 1 - similarity

            # so vec_dist = 0.22 then similarity = 1 - 0.22 = 0.78   , means striclty clustering hona chayiye
            #  vec_dist < best_distance: ye check karega ki current complaint ka distance best_distance se kam hai ya nhi
             
        if vec_dist < 0.22 and vec_dist < best_distance:
            best_distance = vec_dist
            best_group_id = master.get("ctoken") # In earlier schemas this is equivalent to group_id
            best_duplicate_count = master.get("report_count", 1)
            
    if best_group_id:
        logger.info(f"Routed duplicate clone '{complaint_id}' mapping into Group '{best_group_id}'")
        return best_group_id, True, best_duplicate_count, embedding
    else:
        logger.info(f"Routed novel incident '{complaint_id}' establishing independent Master record.")
        return complaint_id, False, 1, embedding
