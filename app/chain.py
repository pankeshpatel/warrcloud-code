"""LangGraph pipeline — extraction → validation → coverage.

Three nodes, each with a single responsibility:

  extract_node  — LLM reads RO text, extracts 8 base fields
  validate_node — Python runs 4 deterministic VIN checks, no LLM
  coverage_node — LLM calls the warranty MCP tool, returns coverage result

State flows through all nodes via ClaimState (TypedDict).
"""

from typing import List, TypedDict

from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph

from app.models import ClaimExtractionBase, CoverageResult

# ── Shared pipeline state ─────────────────────────────────────────────────────


class ClaimState(TypedDict):
    # Input
    ro_text: str
    # extract_node outputs
    vin: str
    year: int
    make: str
    model: str
    mileage: int
    repair_description: str
    part_number: str
    labor_hours: float
    # validate_node outputs
    vin_valid: bool
    vin_issues: List[str]
    # coverage_node outputs
    eligible: bool
    reason: str
    warranty_type: str


# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """You are an automotive warranty claim data extractor.
Extract the following fields from the repair order (RO) text:

- vin: exact 17-character string, no spaces or dashes
- year: 4-digit integer model year
- make: manufacturer name as written (e.g. "Chevrolet", "Ford")
- model: model name as written (e.g. "Bolt EV", "F-150")
- mileage: integer, strip commas and units
- repair_description: copy the "Repair:" field text only — do NOT add context from \
the "Complaint:" field. Keep it short and factual, e.g. "Replaced high-voltage battery module"
- part_number: first part number only, digits only
- labor_hours: float
"""

_COVERAGE_PROMPT = (
    "You are a warranty coverage assistant. "
    "Call the available warranty tool with the vehicle details provided."
)


# ── Node 1 — Extract ──────────────────────────────────────────────────────────


async def extract_node(state: ClaimState) -> dict:
    """LLM extracts 8 base fields from unstructured RO text."""
    agent = create_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=[],
        system_prompt=_EXTRACTION_PROMPT,
        response_format=ClaimExtractionBase,
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": state["ro_text"]}]}
    )
    extracted: ClaimExtractionBase = result["structured_response"]
    return {
        "vin": extracted.vin,
        "year": extracted.year,
        "make": extracted.make,
        "model": extracted.model,
        "mileage": extracted.mileage,
        "repair_description": extracted.repair_description,
        "part_number": extracted.part_number,
        "labor_hours": extracted.labor_hours,
    }


# ── Node 2 — Validate ─────────────────────────────────────────────────────────


def validate_node(state: ClaimState) -> dict:
    """Pure Python VIN validation — no LLM involved.

    Runs 4 checks in order:
      1. Length must be 17 characters             (ISO 3779)
      2. Model-year character (position 10)        (ISO 3779)
      3. WMI (positions 1-3) vs. extracted make   (ISO 3779 / NHTSA)
      4. Check digit (position 9) checksum         (49 CFR Part 565)

    Checks 2-4 are skipped if the VIN is not 17 characters.
    """
    from app.vin_tools import check_vin_model_year, check_vin_wmi, check_vin_checkdigit

    vin = state["vin"]
    issues: List[str] = []

    if len(vin) != 17:
        issues.append(f"VIN is {len(vin)} characters, must be 17")
    else:
        for result in [
            check_vin_model_year(vin, state["year"]),
            check_vin_wmi(vin, state["make"]),
            check_vin_checkdigit(vin),
        ]:
            if not result["pass"]:
                issues.append(result["issue"])

    return {"vin_valid": len(issues) == 0, "vin_issues": issues}


# ── Node 3 — Coverage ─────────────────────────────────────────────────────────


async def coverage_node(state: ClaimState) -> dict:
    """LLM calls the warranty MCP tool and returns coverage result.

    The warranty service runs as a separate MCP server process (stdio transport),
    simulating a real external warranty adjudication API.
    In production: swap the MCP server command for the real external service URL —
    zero changes needed in this file.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    try:
        client = MultiServerMCPClient(
            {
                "warranty": {
                    "command": "python",
                    "args": ["-m", "app.warranty_mcp_server"],
                    "transport": "stdio",
                }
            }
        )
        tools = await client.get_tools()

        agent = create_agent(
            model="anthropic:claude-sonnet-4-6",
            tools=tools,
            system_prompt=_COVERAGE_PROMPT,
            response_format=CoverageResult,
        )

        prompt = (
            f"VIN: {state['vin']}\n"
            f"Make: {state['make']}\n"
            f"Model: {state['model']}\n"
            f"Year: {state['year']}\n"
            f"Mileage: {state['mileage']}\n"
            f"Part Number: {state['part_number']}\n"
            f"Repair Description: {state['repair_description']}"
        )

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]}
        )
        sr: CoverageResult = result["structured_response"]
        return {
            "eligible": sr.eligible,
            "reason": sr.reason,
            "warranty_type": sr.warranty_type,
        }

    except Exception as exc:
        return {
            "eligible": False,
            "reason": f"Coverage check failed: {exc}",
            "warranty_type": "Unknown",
        }


# ── Graph ─────────────────────────────────────────────────────────────────────

_graph = StateGraph(ClaimState)
_graph.add_node("extract", extract_node)
_graph.add_node("validate", validate_node)
_graph.add_node("coverage", coverage_node)
_graph.add_edge(START, "extract")
_graph.add_edge("extract", "validate")
_graph.add_edge("validate", "coverage")
_graph.add_edge("coverage", END)

workflow = _graph.compile()


# ── Public API ────────────────────────────────────────────────────────────────


async def run_claim_pipeline(ro_text: str) -> ClaimState:
    """Run the full extraction → validation → coverage pipeline.

    Raises on extraction failure (caller should return HTTP 422).
    Coverage failures are caught inside coverage_node and returned as
    eligible=False with a reason string — pipeline always completes.
    """
    return await workflow.ainvoke({"ro_text": ro_text})
