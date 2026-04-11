# CitySync: Nagpur Municipal Corporation (NMC) Civic Routing Engine

CitySync is an intelligent administrative backend pipeline designed for the NMC. It leverages multimodal AI classification, physical/semantic vector mapping, and multidimensional priority scoring to automatically categorize citizen complaints, deduplicate mass-reporting, assign rigorous SLAs, and instantly route issues to the correct civic department.

---

## 🏗️ The "Why": Tech Stack Rationale

1. **Python Engine**: The backbone of the routing server. Python natively supports the math, array transformations, and specialized NLP inference tasks required to interpret mixed-language civic complaints on the fly.
2. **MongoDB**: We selected a document-based NoSQL architecture. Civic complaints are inherently flexible (often lacking GPS coordinates, occasionally containing visual data, and relying heavily on parent-child cluster nesting for duplication logic). MongoDB's schema-less topology stores these fluid documents flawlessly.
3. **Google Gemini Flash (Multimodal LLM)**: Traditional keyword logic breaks down across vernacular barriers (English, Hindi, Marathi mixing). We use Gemini Flash to parse messy localized slang natively while simultaneously evaluating images to automatically benchmark *Physical Visual Severity* over purely written frustration.
4. **SentenceTransformers (`all-MiniLM-L6-v2`)**: Rather than trying to parse exact text matches, this incredibly lightweight spatial-embedding model turns semantic meaning into 384-dimensional mathematical vectors. "Pipe broke and flooding" natively maps as a mathematical match with "Water leaking heavily", catching duplicate issues seamlessly.

---

## ⚙️ Module Execution Workflow

The logic of CitySync is cleanly decoupled into 5 operational Python modules. 

### 1. The Central Integrator: `pipeline.py`
This is the master orchestrate gateway. It manages race-conditions and prevents individual module failures from crashing the system (e.g. enforcing safe bounds if a user bypasses GPS mapping or uploads a corrupt image).
- **Inputs**: Raw payload parameters (Text mapping, Optional Image, Lat, Lng, Ward ID) wrapped by the web-framework.
- **Outputs**: A massive combined JSON architecture dict containing absolutely everything regarding the complaint status logic.

### 2. The Neural Analyzer: `classifier.py`
Analyzes physical media and text constraints locally natively overriding inputs based on hard rules.
- **Inputs**: Complaint text (String), local image payload path.
- **Job**: Evaluates dual-weight. If the citizen text registers a "Medium" severity but the visual image identifies an exposed active power line, the system natively locks the output constraint to maximum priority ("Critical").
- **Outputs**: Pure JSON payload classifying: department category, general severity, complaint summary, required immediate action tracking.

### 3. The Clustering Core: `dedup_engine.py`
Reduces UI clutter by linking massive crowdsourced panic reports of identical civic anomalies into unified parent incident tracking cards for the Admin Dashboard.
- **Inputs**: Incident Text, Latitude/Longitude, Category array, and MongoDB connection pipeline.
- **Job**: 
  - Converts the text to a dense vector embedding. 
  - Iterates over local open reports within 14 days inside the matching category.
  - Generates a **Haversine Math distance (<300m)** constraint and a **Cosine Vector (<0.22)** semantic mapping natively.
  - Triggers Parent / Child array groupings dictating the `is_master` mapping flags for Dashboard APIs.
- **Outputs**: A group relationship ID (`group_id`) natively committing cloned/master assignment mappings. 

### 4. The SLA Controller: `priority_scorer.py`
Calculates customized deadlines. Does not treat all potholes equally.
- **Inputs**: Calculated Gemini Severity, Total deduplicated duplicate density arrays, and mapped Ward Vulnerability mappings.
- **Job**: An intricate 100-point algorithm bounds time-delays against duplicates mapping explicitly bounding issues in extremely vulnerable municipal districts with shorter countdowns natively.
- **Outputs**: Priority constraint (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) and exact integer Hour SLA boundaries (4h, 24h, 72h).

### 5. The Routing Dispatcher: `router.py`
The legacy API resolving structural endpoints to human beings. 
- **Inputs**: AI output, Score constraints, Ward logic constraints.
- **Job**: Cross-references local NMC tables identifying natively which exact civil officer commands mapping specific domains within precise regional wards natively appending notification structures based exactly on SLA timeouts. 
- **Outputs**: Detailed notification alerts appending officer emails, phone lines, reasons for structural assignment bounding.

---

*This document is a living architecture tracker. Modules map symmetrically to ensure decoupled logic limits database interference cleanly.*
