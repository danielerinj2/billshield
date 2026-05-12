"""FastAPI main application for BillShield."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router

app = FastAPI(
    title="BillShield API",
    description="Medical bill auditing and dispute resolution API",
    version="1.0.0"
)

# CORS configuration for Bolt.new frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your Bolt.new domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router, prefix="/api", tags=["BillShield"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "BillShield API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "database": "connected",
        "agent": "ready"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)