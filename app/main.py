"""FastAPI application — warranty claim analysis API."""

import logging
import logging.config
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.chain import run_claim_pipeline
from app.models import ClaimRecord, ClaimRequest, ClaimResponse, ErrorResponse
from app.store import get_claim, save_claim

load_dotenv()

# ── Structured JSON logging ───────────────────────────────────────────────────

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            "fmt": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"level": "INFO", "handlers": ["console"]},
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


# ── App lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("WarrCloud Claim Analysis API starting up")
    yield
    logger.info("WarrCloud Claim Analysis API shutting down")


app = FastAPI(
    title="WarrCloud Claim Analysis API",
    description="Extracts structured data from repair orders and checks warranty coverage.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post(
    "/analyze-claim",
    response_model=ClaimResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Analyze a repair order and determine warranty coverage",
)
async def analyze_claim(request: ClaimRequest) -> ClaimResponse:
    claim_id = str(uuid.uuid4())
    logger.info("analyze_claim: received request", extra={"claim_id": claim_id})

    try:
        state = await run_claim_pipeline(request.ro_text)
        logger.info(
            "analyze_claim: pipeline complete",
            extra={
                "claim_id": claim_id,
                "vin": state["vin"],
                "vin_valid": state["vin_valid"],
                "eligible": state["eligible"],
                "warranty_type": state["warranty_type"],
            },
        )
    except Exception as exc:
        logger.error(
            "analyze_claim: pipeline failed",
            extra={"claim_id": claim_id, "error": str(exc)},
        )
        raise HTTPException(status_code=422, detail=f"Claim pipeline failed: {exc}")

    response = ClaimResponse(
        claim_id=claim_id,
        vin=state["vin"],
        year=state["year"],
        make=state["make"],
        model=state["model"],
        mileage=state["mileage"],
        repair_description=state["repair_description"],
        part_number=state["part_number"],
        labor_hours=state["labor_hours"],
        vin_valid=state["vin_valid"],
        vin_issues=state["vin_issues"],
        coverage_eligible=state["eligible"],
        coverage_reason=state["reason"],
        warranty_type=state["warranty_type"],
    )
    save_claim(ClaimRecord(**response.model_dump(), ro_text=request.ro_text))
    logger.info("analyze_claim: complete", extra={"claim_id": claim_id})
    return response


@app.get(
    "/claims/{claim_id}",
    response_model=ClaimRecord,
    responses={404: {"model": ErrorResponse}},
    summary="Retrieve a previously analyzed claim",
)
async def get_claim_by_id(claim_id: str) -> ClaimRecord:
    record = get_claim(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found")
    return record


@app.get("/health", summary="Health check")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
