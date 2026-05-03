from typing import List, Optional
from pydantic import BaseModel, Field


class ClaimRequest(BaseModel):
    ro_text: str = Field(..., description="Unstructured repair order text")


class ClaimExtractionBase(BaseModel):
    """8 base fields extracted from RO text by the LLM (extract_node).
    No VIN validation fields — those are written by validate_node."""

    vin: str = Field(..., description="17-character Vehicle Identification Number")
    year: int = Field(..., description="Vehicle model year")
    make: str = Field(..., description="Vehicle manufacturer, e.g. Chevrolet")
    model: str = Field(..., description="Vehicle model name, e.g. Bolt EV")
    mileage: int = Field(..., description="Odometer reading at time of repair")
    repair_description: str = Field(..., description="Concise description of repair performed")
    part_number: str = Field(..., description="Primary part number used in the repair")
    labor_hours: float = Field(..., description="Total labor hours")


class ClaimExtraction(ClaimExtractionBase):
    """Full extraction including VIN validation results (written by validate_node)."""

    vin_valid: bool = Field(..., description="True if VIN passes all structural and consistency checks")
    vin_issues: List[str] = Field(
        default_factory=list,
        description=(
            "Failing checks only — one short phrase per issue. "
            "Empty list when vin_valid is true."
        ),
    )


class CoverageResult(BaseModel):
    eligible: bool
    reason: str
    warranty_type: str


class ClaimResponse(BaseModel):
    claim_id: str
    vin: str
    year: int
    make: str
    model: str
    mileage: int
    repair_description: str
    part_number: str
    labor_hours: float
    vin_valid: bool
    vin_issues: List[str]
    coverage_eligible: bool
    coverage_reason: str
    warranty_type: str


class ClaimRecord(ClaimResponse):
    """Persisted claim including the original RO text."""

    ro_text: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
