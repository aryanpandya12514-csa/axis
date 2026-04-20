import os
import json
import logging
import time
from typing import Dict, Any, Optional
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def build_system_prompt() -> str:
    """
    Returns the full system prompt string that instructs Gemini on
    how to analyze civic complaints and return structured JSON.
    """
    return """You are CitySync, a municipal complaint classifier for Nagpur Municipal Corporation (NMC), India.
Your task is to analyze civic complaints based on text (in English, Hindi, or Marathi) and an optional image.

Perform THREE analysis steps in parallel:

STEP 1 — TEXT SENTIMENT & INTENT ANALYSIS
- Detect the sentiment of the text: urgent / frustrated / neutral / reporting
- Extract the civic issue type from the text description
- Detect language (english / hindi / marathi / mixed)
- Extract any location mentioned in the text
- Assess severity based on the text: 0 (low), 1 (medium), 2 (critical)

STEP 2 — IMAGE ANALYSIS
- If an image is provided, visually identify what civic problem is shown.
- Assess severity from the image: 0 (low), 1 (medium), 2 (critical).
- Describe what is visually detected (e.g., "large pothole with water", "overflowing garbage bin").
- If no image is provided, return neutral/empty image fields (e.g. empty strings, severity 0).

STEP 3 — FUSION & DEPARTMENT ROUTING
Combine text analysis result + image analysis result.
Rules for severity:
- If image severity > text severity -> trust the image (visual evidence wins).
- If text says URGENT (severity 2) but image shows minor issue (severity 0 or 1) -> keep severity at 1 (medium).
- If both agree -> use that severity.

Map the final combined analysis to exactly ONE municipal department from this list:
- "PWD - Public Works Department" -> pothole, road damage, broken road
- "Electrical Department" -> streetlight, power outage, exposed wire
- "Solid Waste Management" -> garbage, waste, overflowing bin
- "NMC Water Supply Department" -> no water, contaminated water, low pressure
- "Drainage Department" -> sewage, blocked drain, manhole, flooding
- "Encroachment Removal Cell" -> illegal construction, footpath blocked
- "Environment Department" -> noise, pollution, tree cutting
- "Animal Husbandry Department" -> stray dogs, stray cattle, animal nuisance
- "Garden Department" -> fallen tree, dangerous branch
- "Building & Structural Department" -> collapsed wall, unsafe building, crack
- "General Grievance Cell" -> anything that does not match above

OUTPUT FORMAT
Return a pure JSON object using this exact structure (do not include markdown formatting or comments):
{
  "text_analysis": {
    "sentiment": "urgent" | "frustrated" | "neutral" | "reporting",
    "issue_type": "",
    "language": "english" | "hindi" | "marathi" | "mixed",
    "location_hint": "",
    "text_severity": 0 | 1 | 2
  },
  "image_analysis": {
    "visual_description": "",
    "detected_issue": "",
    "image_severity": 0 | 1 | 2
  },
  "final_result": {
    "category": "",
    "severity": 0 | 1 | 2,
    "severity_label": "low" | "medium" | "critical",
    "department": "",
    "needs_immediate_action": true | false,
    "summary": "<12 word max summary of the complaint>",
    "confidence": 0.0 to 1.0,
    "routing_reason": ""
  }
}
"""

def load_model() -> genai.GenerativeModel:
    """
    Initializes and returns the Gemini model with the system prompt.
    """
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        logger.warning("GEMINI_API_KEY environment variable is not set!")
        
    system_instruction = build_system_prompt()
    
    _model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            response_mime_type="application/json" 
        )
    )
    return _model

logger.info("Initializing CitySync Model...")
model = load_model()

def _get_fallback_result(reason: str, text: str) -> Dict[str, Any]:
    logger.error(f"Classification failed with Cloud API limitation. Initializing Local Regex Fallback. Reason: {reason}")
    text_lower = text.lower()
    
    category = "general issue"
    department = "General Grievance Cell"
    sentiment = "reporting"
    severity = 1
    
    # Primitive rule-engine for Local Fallback
    if "pothole" in text_lower or "road" in text_lower:
        category = "pothole/road damage"
        department = "PWD - Public Works Department"
        severity = 2 if "dangerous" in text_lower or "huge" in text_lower else 1
    elif "water" in text_lower or "pipeline" in text_lower:
        category = "water supply"
        department = "NMC Water Supply Department"
        severity = 2 if "no water" in text_lower else 1
    elif "garbage" in text_lower or "waste" in text_lower or "bin" in text_lower:
        category = "waste accumulation"
        department = "Solid Waste Management"
    elif "wire" in text_lower or "electricity" in text_lower or "light" in text_lower:
        category = "electrical hazard"
        department = "Electrical Department"
        severity = 2
    elif "drain" in text_lower or "sewage" in text_lower:
        category = "drainage issue"
        department = "Drainage Department"
        severity = 2
        
    return {
        "text_analysis": {
            "sentiment": "urgent" if severity == 2 else "neutral",
            "issue_type": category,
            "language": "english",
            "location_hint": "Unknown",
            "text_severity": severity
        },
        "image_analysis": {
            "visual_description": "API fallback invoked, image parsing suspended",
            "detected_issue": "",
            "image_severity": 0
        },
        "final_result": {
            "category": category,
            "severity": severity,
            "severity_label": "critical" if severity == 2 else ("low" if severity == 0 else "medium"),
            "department": department,
            "needs_immediate_action": bool(severity == 2),
            "summary": " ".join(text.split()[:10]) + "...", # Truncate first 10 words as summary
            "confidence": 0.65,
            "routing_reason": f"System Fallback Matched keywords for '{category}' automatically due to Cloud API Lockout."
        }
    }

def _parse_gemini_response(raw_text: str) -> Dict[str, Any]:
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[len("```json"):].strip()
    elif cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:].strip()
        
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3].strip()
    
    try:
        parsed_dict = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}\nRaw text was:\n{raw_text}")
        raise ValueError("Malformed JSON returned by Gemini")
        
    required_keys = ["text_analysis", "image_analysis", "final_result"]
    for k in required_keys:
        if k not in parsed_dict:
            raise ValueError(f"Missing required key '{k}' in parsed JSON")
            
    return parsed_dict

def classify_complaint(text: str, image_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Main multimodal grouping function that takes a text string and optional image.
    """
    inputs = [text]
    
    if image_path:
        try:
            img = Image.open(image_path)
            # Resize image to save bandwidth and token processing costs
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            inputs.append(img)
        except Exception as e:
            logger.warning(f"Failed to load image from {image_path}: {e}")

    retry_count = 1
    for attempt in range(retry_count + 1):
        try:
            response = model.generate_content(inputs)
            if not response.text:
                raise ValueError("Response text is empty")
            return _parse_gemini_response(response.text)
        except Exception as e:
            if attempt < retry_count:
                logger.warning(f"API call failed: {e}. Retrying after 3 seconds...")
                time.sleep(3)
            else:
                return _get_fallback_result(str(e), text)


if __name__ == "__main__":
    print("====== Running CitySync Classifier Tests ======\n")
    
    # Text-only test
    print("--- Test 1: Pothole (Text Only) ---")
    pothole_res = classify_complaint("Huge pothole on Wardha road, very dangerous for bikes.")
    print(json.dumps(pothole_res, indent=2))
    print("\n==================================================\n")
    
    # Test Fake/Missing image
    print("--- Test 2: Missing Image ---")
    garbage_res = classify_complaint("Garbage overflowing outside NMC school here.", "fake_missing.jpg")
    print(json.dumps(garbage_res, indent=2))
    print("\n==================================================\n")
