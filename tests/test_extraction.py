"""
Unit tests for extraction parsing, warranty stub, store, and API routes.

LLM calls are mocked via run_claim_pipeline — only warranty stub logic and
FastAPI routes hit real code.
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models import ClaimExtraction, ClaimRecord
from app.warranty import check_warranty_coverage
from app.store import save_claim, get_claim

# ── Shared fixtures ───────────────────────────────────────────────────────────

RO_TEXT = (
    "RO# 847291 | VIN: 1G1FY6S00N0000123 | 2022 Chevrolet Bolt EV | "
    "Mileage: 12,340 | Complaint: Battery warning light on, reduced range. | "
    "Repair: Replaced high-voltage battery module. | Parts: 24299461 "
    "(Battery Module Assembly) | Labor: 4.2 hrs | Tech: M. Rodriguez"
)

# Used by store tests — full ClaimExtraction with VIN validation results
VALID_EXTRACTION = ClaimExtraction(
    vin="1G1FY6S00N0000123",
    year=2022,
    make="Chevrolet",
    model="Bolt EV",
    mileage=12340,
    repair_description="Replaced high-voltage battery module",
    part_number="24299461",
    labor_hours=4.2,
    vin_valid=False,
    vin_issues=["Check digit (position 9) does not match calculated value"],
)

# Mocked return value for run_claim_pipeline — matches ClaimState TypedDict
VALID_STATE = {
    "ro_text": RO_TEXT,
    "vin": "1G1FY6S00N0000123",
    "year": 2022,
    "make": "Chevrolet",
    "model": "Bolt EV",
    "mileage": 12340,
    "repair_description": "Replaced high-voltage battery module",
    "part_number": "24299461",
    "labor_hours": 4.2,
    "vin_valid": False,
    "vin_issues": ["Check digit (position 9) does not match calculated value"],
    "eligible": True,
    "reason": "Vehicle within Voltec warranty: 8yr/100k miles",
    "warranty_type": "Voltec",
}


# ── Warranty stub tests ───────────────────────────────────────────────────────


class TestWarrantyCoverage:
    def test_voltec_eligible(self):
        result = check_warranty_coverage(
            vin="1G1FY6S00N0000123",
            make="Chevrolet",
            model="Bolt EV",
            year=2022,
            mileage=12_340,
            part_number="24299461",
            repair_description="Replaced high-voltage battery module",
        )
        assert result["eligible"] is True
        assert result["warranty_type"] == "Voltec"

    def test_voltec_expired_mileage(self):
        result = check_warranty_coverage(
            vin="1G1FY6S00N0000123",
            make="Chevrolet",
            model="Bolt EV",
            year=2015,
            mileage=105_000,
            part_number="24299461",
            repair_description="Replaced high-voltage battery module",
        )
        assert result["eligible"] is False
        assert result["warranty_type"] == "Voltec"

    def test_bumper_to_bumper_eligible(self):
        result = check_warranty_coverage(
            vin="1FTFW1E53NFA12345",
            make="Ford",
            model="F-150",
            year=2023,
            mileage=10_000,
            part_number="99999999",
            repair_description="Replaced windshield wiper motor",
        )
        assert result["eligible"] is True
        assert result["warranty_type"] == "Bumper-to-Bumper"

    def test_powertrain_eligible(self):
        result = check_warranty_coverage(
            vin="1FTFW1E53NFA12345",
            make="Ford",
            model="F-150",
            year=2021,
            mileage=45_000,
            part_number="99999999",
            repair_description="Rebuilt engine block and replaced crankshaft",
        )
        assert result["eligible"] is True
        assert result["warranty_type"] == "Powertrain"

    def test_no_coverage(self):
        result = check_warranty_coverage(
            vin="1FTFW1E53NFA12345",
            make="Ford",
            model="F-150",
            year=2015,
            mileage=90_000,
            part_number="99999999",
            repair_description="Replaced door handle",
        )
        assert result["eligible"] is False
        assert result["warranty_type"] == "None"

    def test_invalid_vin_raises(self):
        with pytest.raises(ValueError, match="Invalid VIN"):
            check_warranty_coverage(
                vin="TOOSHORT",
                make="Ford",
                model="F-150",
                year=2022,
                mileage=10_000,
                part_number="99999999",
            )

    def test_unknown_make_raises(self):
        with pytest.raises(ValueError, match="Unknown make"):
            check_warranty_coverage(
                vin="1G1FY6S00N0000123",
                make="Lada",
                model="Niva",
                year=2022,
                mileage=10_000,
                part_number="99999999",
            )


# ── VIN validation tests ──────────────────────────────────────────────────────


class TestVinTools:
    def test_valid_vin_passes_all_checks(self):
        from app.vin_tools import check_vin_model_year, check_vin_wmi, check_vin_checkdigit
        # 1G1AB5SX3N0000001 — valid WMI, valid year char, valid check digit
        assert check_vin_model_year("1G1AB5SX3N0000001", 2022)["pass"] is True
        assert check_vin_wmi("1G1AB5SX3N0000001", "Chevrolet")["pass"] is True
        assert check_vin_checkdigit("1G1AB5SX3N0000001")["pass"] is True

    def test_check_digit_failure(self):
        from app.vin_tools import check_vin_checkdigit
        result = check_vin_checkdigit("1G1FY6S00N0000123")
        assert result["pass"] is False
        assert result["issue"] == "Check digit (position 9) does not match calculated value"

    def test_wmi_mismatch(self):
        from app.vin_tools import check_vin_wmi
        result = check_vin_wmi("1FTEW1CP5NA000001", "Chevrolet")
        assert result["pass"] is False
        assert "1FT" in result["issue"]
        assert "Ford" in result["issue"]

    def test_model_year_mismatch(self):
        from app.vin_tools import check_vin_model_year
        result = check_vin_model_year("1G1AB5SX3N0000001", 2023)
        assert result["pass"] is False
        assert "'N'" in result["issue"]

    def test_short_vin(self):
        from app.vin_tools import check_vin_checkdigit
        result = check_vin_checkdigit("1G1AB5SX3N000")
        assert result["pass"] is False


# ── In-memory store tests ─────────────────────────────────────────────────────


class TestStore:
    def test_save_and_retrieve(self):
        record = ClaimRecord(
            claim_id="test-id-001",
            ro_text=RO_TEXT,
            **VALID_EXTRACTION.model_dump(),
            coverage_eligible=True,
            coverage_reason="Vehicle within Voltec warranty: 8yr/100k miles",
            warranty_type="Voltec",
        )
        save_claim(record)
        retrieved = get_claim("test-id-001")
        assert retrieved is not None
        assert retrieved.vin == "1G1FY6S00N0000123"

    def test_missing_claim_returns_none(self):
        assert get_claim("does-not-exist") is None


# ── API integration tests (pipeline mocked) ───────────────────────────────────


@pytest.fixture
def mock_pipeline():
    """Patch run_claim_pipeline so no real LLM or MCP calls are made."""
    with patch(
        "app.main.run_claim_pipeline", new=AsyncMock(return_value=VALID_STATE)
    ):
        yield


@pytest.fixture
def mock_pipeline_error():
    """Patch run_claim_pipeline to simulate a pipeline failure."""
    with patch(
        "app.main.run_claim_pipeline",
        new=AsyncMock(side_effect=Exception("connection timeout")),
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_analyze_claim_success(mock_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/analyze-claim", json={"ro_text": RO_TEXT})

    assert response.status_code == 200
    data = response.json()
    assert data["vin"] == "1G1FY6S00N0000123"
    assert data["coverage_eligible"] is True
    assert data["warranty_type"] == "Voltec"
    assert data["vin_valid"] is False
    assert data["vin_issues"] == ["Check digit (position 9) does not match calculated value"]
    assert "claim_id" in data


@pytest.mark.asyncio
async def test_analyze_claim_pipeline_failure(mock_pipeline_error):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/analyze-claim", json={"ro_text": "garbage text"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_claim_not_found():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/claims/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_claim_after_analyze(mock_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        post_resp = await client.post("/analyze-claim", json={"ro_text": RO_TEXT})
        assert post_resp.status_code == 200
        claim_id = post_resp.json()["claim_id"]

        get_resp = await client.get(f"/claims/{claim_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["claim_id"] == claim_id


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
