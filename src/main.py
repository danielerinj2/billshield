"""
BillShield API — entry point.
Lovable frontend will call these endpoints.
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="BillShield API",
    description="Hospital bill analysis for Indian patients",
    version="0.1.0",
)

# Allow Lovable to call from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("data/uploaded")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version="0.1.0")


@app.get("/")
def root():
    return {
        "service": "BillShield API",
        "docs_url": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    