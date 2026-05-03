"""
MCP server that exposes check_warranty_coverage as an external tool.

The challenge treats check_warranty_coverage() as a third-party warranty
adjudication service. This MCP server wraps it so the LangChain agent
integrates with it via the Model Context Protocol — the same way it would
call a real external warranty API in production.

Run standalone (stdio transport, used by chain.py as a subprocess):
    python -m app.warranty_mcp_server
"""

from mcp.server.fastmcp import FastMCP

from app.warranty import check_warranty_coverage

mcp = FastMCP("warranty-coverage-service")


@mcp.tool()
def check_warranty(
    vin: str,
    make: str,
    model: str,
    year: int,
    mileage: int,
    part_number: str,
    repair_description: str = "",
) -> dict:
    """
    Check warranty coverage eligibility for a vehicle and repair.

    Returns a dict with:
      eligible (bool)      — whether the repair is covered
      reason (str)         — human-readable explanation
      warranty_type (str)  — Voltec | Powertrain | Bumper-to-Bumper | None
    """
    return check_warranty_coverage(
        vin=vin,
        make=make,
        model=model,
        year=year,
        mileage=mileage,
        part_number=part_number,
        repair_description=repair_description,
    )


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
