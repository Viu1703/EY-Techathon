from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import json
import io
import traceback

app = FastAPI()
app.mount("/evidence", StaticFiles(directory="D:/TY-SEM1/EY-Techathon/provider-guardian/mock_data/evidence"), name="evidence")
# --- CORS SETUP (Crucial for Frontend) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load Truth DB
TRUTH_DB_PATH = "../mock_data/registry_truth.json"
try:
    with open(TRUTH_DB_PATH, "r") as f:
        TRUTH_DB = json.load(f)
    print("✅ Truth Database Loaded")
except FileNotFoundError:
    print(f"⚠️ Truth DB not found at {TRUTH_DB_PATH}. Using empty DB.")
    TRUTH_DB = {}

@app.get("/")
def home():
    return {"message": "Provider Data Guardian API is running"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    print(f"📥 Receiving file: {file.filename}")  # <--- IF YOU DON'T SEE THIS IN TERMINAL, CODE DIDN'T UPDATE
    
    try:
        # 1. READ THE FILE
        contents = await file.read()
        
        # 2. DECODE THE CSV (Handle Excel formatting issues)
        try:
            decoded_content = contents.decode('utf-8-sig')
        except UnicodeDecodeError:
            decoded_content = contents.decode('latin-1') 
            
        df = pd.read_csv(io.StringIO(decoded_content))
        
        # 3. VERIFY COLUMNS
        required_col = 'npi'
        if required_col not in df.columns:
            # Fallback: if Excel smashed everything into one column, try separating by comma explicitly
            if len(df.columns) == 1: 
                print("⚠️ CSV parsing issue. Trying strict comma separator.")
                df = pd.read_csv(io.StringIO(decoded_content), sep=',', engine='python')
        
        if required_col not in df.columns:
             return JSONResponse(status_code=400, content={"detail": f"CSV Error: Could not find 'npi' column. Found: {list(df.columns)}"})

        # 4. PROCESS RECORDS
        records = df.to_dict(orient="records")
        results = []
        
        for record in records:
            npi_str = str(record.get('npi', '')).replace('.0', '') # Remove decimals if Excel added them
            
            validation_status = "Verified"
            confidence_score = 100
            issues = []
            
            if npi_str in TRUTH_DB:
                truth = TRUTH_DB[npi_str]
                
                # Address Check
                input_addr = str(record.get('address', '')).lower().split(',')[0]
                truth_addr = str(truth.get('address', '')).lower()
                
                if input_addr not in truth_addr:
                    validation_status = "Flagged"
                    confidence_score = 45
                    issues.append(f"Address Mismatch: Registry has '{truth['address']}'")
                
                # License Check
                if str(record.get('license_status')) != str(truth.get('license_status')):
                    validation_status = "Flagged"
                    confidence_score = 30
                    issues.append(f"License Status: Registry says '{truth['license_status']}'")
            else:
                validation_status = "Unknown"
                confidence_score = 0
                issues.append("Provider NPI not found.")

            results.append({
                "npi": npi_str,
                "name": f"{record.get('first_name', '')} {record.get('last_name', '')}",
                "validation_status": validation_status,
                "confidence_score": confidence_score,
                "issues": issues,
                "evidence_source": TRUTH_DB.get(npi_str, {}).get("source", "N/A")
            })
            
        print(f"✅ Successfully processed {len(results)} rows")
        return {"status": "success", "data": results}

    except Exception as e:
        print("❌ CRITICAL ERROR IN BACKEND:")
        traceback.print_exc() # This prints the REAL error to your terminal
        return JSONResponse(status_code=500, content={"detail": str(e)})