# CitySync: Intelligent Urban Complaint Routing Engine 🏙️

CitySync is an intelligent, citizen-centric administrative backend pipeline designed for the Nagpur Municipal Corporation (NMC). It leverages multimodal AI classification, spatial vector mapping, and multidimensional priority scoring to automatically categorize civic complaints, deduplicate mass-reporting, assign rigorous SLAs, and instantly route issues to the correct civic department via a live React dashboard.

## 🚀 Key Features
1. **Direct Messaging Integration:** Citizens submit complaints and photos natively through a conversational WhatsApp webhook gateway.
2. **Multimodal AI Classification:** Evaluates both citizen text and image severity simultaneously using an intelligent vision-language engine.
3. **Semantic & Spatial Deduplication:** Merges identical complaints locally using 384D vector math and 300m GPS bounding.
4. **Dynamic SLA Priority Scoring:** Calculates response deadlines based on ward vulnerability and report frequency.
5. **Real-Time Command Center:** React + Tailwind dashboard with live Leaflet.js geo-tag visualization.

---

## 🏗️ The Tech Stack

* **Backend Framework:** Python / Flask
* **Database:** MongoDB (PyMongo) - *Chosen for schema-less flexibility with fluid complaint structures.*
* **AI Engine:** Multimodal Vision-Language Classification Model
* **NLP Vectorization:** SentenceTransformers (`all-MiniLM-L6-v2`) - *Running locally for semantic mapping.*
* **Frontend:** React (Vite), Tailwind CSS, React-Leaflet
* **Gateway:** Custom Secure Webhook Architecture

---

## ⚙️ Core Architecture & Module Workflow

The logic of CitySync is cleanly decoupled into purely functional Python modules, ensuring the database operations remain safely isolated in the Flask routing layer.

### 1. The Central Integrator: `pipeline.py`
The master orchestrator. It manages race-conditions, handles GPS fail-safes, and coordinates the isolated evaluation models entirely in-memory using data arrays fetched by the PyMongo hook.

### 2. The Neural Analyzer: `classifier.py`
The Multimodal brain. It analyzes physical media and text constraints. 
* *Dual-Weight Logic:* If visual evidence in an image dictates a higher hazard than the written text, the visual severity natively overrides the text constraint. 
* *Output:* Classifies the specific NMC department, general severity, and flags if immediate action is required.

### 3. The Clustering Core: `dedup_engine.py`
Reduces UI clutter by linking massive crowdsourced panic reports of identical civic anomalies into unified parent-child clusters.
* *Spatial Constraint:* Uses **Haversine Math** to enforce a strict <300m radius check.
* *Semantic Constraint:* Translates text into dense embeddings locally and applies **Cosine Distance (<0.22)** to guarantee conceptual linkage without external API calls.
* *Output:* Returns a unified `group_id` mapping.

### 4. The SLA Controller: `priority_scorer.py`
An intricate 100-point algorithm that bounds time-delays against real-world urban vulnerability.
* *Logic:* Base Severity + Duplicate Density + Temporal Decay + **Ward Vulnerability Multiplier**.
* *Output:* Generates strict Priority bounds (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) and exact SLA countdowns (4h, 24h, 72h).

### 5. The Routing Dispatcher: `router.py`
Cross-references local NMC tables to identify the exact civil officer commanding the specific domain within the precise regional ward. It appends notification structures and generates the final JSON payload for MongoDB insertion.