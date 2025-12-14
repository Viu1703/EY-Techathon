from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from thefuzz import fuzz
import pandas as pd
import json
import io
import traceback
import random
import time

app = FastAPI()

# 1. CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Serve Evidence Images
app.mount("/evidence", StaticFiles(directory="../mock_data/evidence"), name="evidence")

# 3. Load Local Truth DB
TRUTH_DB_PATH = "../mock_data/registry_truth.json"
try:
    with open(TRUTH_DB_PATH, "r") as f:
        TRUTH_DB = json.load(f)
except FileNotFoundError:
    TRUTH_DB = {}

# --- INDIAN REGISTRY AGENT (SIMULATION) ---
def fetch_indian_registry_data(reg_no):
    """
    Simulates a live connection to the National Medical Commission (NMC) / IMR.
    Returns realistic Indian doctor data based on the Registration Number.
    """
    # DEMO DOCTOR 1: Dr. Rajesh Verma (The "Verified" Case)
    if reg_no == "MCI-556677":
        time.sleep(1.2) # Network delay simulation
        return {
            "source": "National Medical Commission (NMC) - Live",
            "name": "Dr. Rajesh Verma",
            "address": "Lotus Hospital, Sector 62, Noida, Uttar Pradesh 201301",
            "license_status": "Active (Permanent)",
            "specialty": "Cardiology",
            "last_updated": "2025-11-10",
            "lat": 28.6208, # Noida
            "lon": 77.3639
        }
        
    # DEMO DOCTOR 2: Dr. Ananya Iyer (The "Mismatch" Case)
    if reg_no == "MCI-998877":
        time.sleep(1.0)
        return {
            "source": "National Medical Commission (NMC) - Live",
            "name": "Dr. Ananya Iyer",
            "address": "Apollo Clinic, Koramangala, Bangalore, Karnataka 560034",
            "license_status": "Active",
            "specialty": "Pediatrics",
            "last_updated": "2025-10-05",
            "lat": 12.9352, # Bangalore
            "lon": 77.6245
        }

    # DEMO DOCTOR 3: Dr. Suresh Patel (The "Expired" Case)
    if reg_no == "MCI-112233":
        time.sleep(1.5)
        return {
            "source": "Indian Medical Registry (IMR)",
            "name": "Dr. Suresh Patel",
            "address": "Civil Lines, Nagpur, Maharashtra 440001",
            "license_status": "Suspended / Expired",
            "specialty": "Orthopedics",
            "last_updated": "2024-01-15",
            "lat": 21.1458, # Nagpur
            "lon": 79.0882
        }

    return None

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        try:
            decoded_content = contents.decode('utf-8-sig')
        except UnicodeDecodeError:
            decoded_content = contents.decode('latin-1') 
            
        df = pd.read_csv(io.StringIO(decoded_content))
        
        # Smart Column Detection: Handle 'npi' or 'reg_no'
        id_col = 'reg_no' if 'reg_no' in df.columns else 'npi'
        
        if id_col not in df.columns:
             return JSONResponse(status_code=400, content={"detail": "CSV missing 'reg_no' column."})

        records = df.to_dict(orient="records")
        results = []
        
        for record in records:
            reg_str = str(record.get(id_col, '')).replace('.0', '')
            
            validation_status = "Unknown"
            confidence_score = 0
            issues = []
            evidence_type = "none" 
            evidence_data = {}
            evidence_source = "N/A"
            
            # 1. CHECK LOCAL TRUTH DB
            truth_data = TRUTH_DB.get(reg_str)
            
            if truth_data:
                evidence_type = "image"
                evidence_data = {"url": f"http://127.0.0.1:8000/evidence/{reg_str}.png"}
                evidence_source = truth_data.get("source")
            else:
                # 2. CHECK INDIAN LIVE REGISTRY AGENT
                truth_data = fetch_indian_registry_data(reg_str)
                if truth_data:
                    evidence_type = "live_data"
                    evidence_data = truth_data
                    evidence_source = "National Medical Commission (NMC)"
            
            # 3. AI VALIDATION LOGIC
            if truth_data:
                input_addr = str(record.get('address', ''))
                truth_addr = str(truth_data.get('address', ''))
                
                # Fuzzy Match Address
                addr_score = fuzz.token_sort_ratio(input_addr, truth_addr)
                
                if addr_score >= 80:
                    confidence_score = 98
                    validation_status = "Verified"
                elif 50 <= addr_score < 80:
                    validation_status = "Flagged"
                    confidence_score = addr_score
                    issues.append(f"Address Ambiguity ({addr_score}%): Registry has '{truth_addr}'")
                else:
                    validation_status = "Flagged"
                    confidence_score = addr_score
                    issues.append(f"Address Mismatch: Registry has '{truth_addr}'")

                # Check License Status
                input_lic = str(record.get('license_status', '')).lower()
                truth_lic = str(truth_data.get('license_status', '')).lower()
                
                if "active" in truth_lic and "active" not in input_lic:
                     validation_status = "Flagged"
                     confidence_score -= 30
                     issues.append(f"License Mismatch: Registry says '{truth_data['license_status']}'")
                elif "expired" in truth_lic or "suspended" in truth_lic:
                     validation_status = "Flagged"
                     confidence_score = 0
                     issues.append(f"CRITICAL: License is {truth_data['license_status']}")

                confidence_score = max(0, min(100, confidence_score))
            else:
                issues.append("Provider Registration Number not found in NMC/MCI Registry.")

            results.append({
                "npi": reg_str, # Keep 'npi' key for frontend compatibility
                "name": f"{record.get('first_name', '')} {record.get('last_name', '')}",
                "validation_status": validation_status,
                "confidence_score": confidence_score,
                "issues": issues,
                "evidence_source": evidence_source,
                "evidence_type": evidence_type,
                "evidence_data": evidence_data
            })
            
        return {"status": "success", "data": results}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})