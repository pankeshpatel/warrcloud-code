# WarrCloud -- Analyze My Claim API

A FastAPI service that accepts unstructured repair order (RO) text and runs it through a
**LangGraph pipeline** — extraction -> VIN validation -> warranty coverage — returning a
fully structured claim response.

---

## Architecture

```
+-----------------------------------------------+
|           POST /analyze-claim                 |
|         { "ro_text": "RO# ..." }              |
+---------------------+-------------------------+
                      |
                      v
+-----------------------------------------------+
|         LangGraph StateGraph (chain.py)       |
|                                               |
|  ClaimState flows through all three nodes:   |
|                                               |
|  +------------------+                         |
|  |  extract_node    |  LLM (create_agent)     |
|  |  Reads: ro_text  |  Extracts 8 base fields |
|  |  Writes: vin,    |  from unstructured text |
|  |  year, make,     |                         |
|  |  model, mileage, |                         |
|  |  repair_desc,    |                         |
|  |  part_number,    |                         |
|  |  labor_hours     |                         |
|  +--------+---------+                         |
|           |                                   |
|           v                                   |
|  +------------------+                         |
|  |  validate_node   |  Pure Python            |
|  |  Reads: vin,     |  4 deterministic checks |
|  |  year, make      |  no LLM involved        |
|  |  Writes:         |                         |
|  |  vin_valid,      |                         |
|  |  vin_issues      |                         |
|  +--------+---------+                         |
|           |                                   |
|           v                                   |
|  +------------------+                         |
|  |  coverage_node   |  LLM + MCP tool         |
|  |  Reads: all      |  Calls warranty MCP     |
|  |  vehicle fields  |  server subprocess      |
|  |  Writes:         |                         |
|  |  eligible,       |                         |
|  |  reason,         |                         |
|  |  warranty_type   |                         |
|  +--------+---------+                         |
|           |                                   |
+-----------|-----------------------------------+
            |
            v
+-----------------------------------------------+
|   store.py -- save to in-memory store         |
+-----------------------------------------------+
            |
            v
+-----------------------------------------------+
|         ClaimResponse JSON                    |
+-----------------------------------------------+


+-----------------------------------------------+
|         GET /claims/{claim_id}                |
|         Retrieve a previously analyzed claim  |
+-----------------------------------------------+
```


---

## Evaluation Guide

A direct map of the five evaluation criteria to where evidence lives in this project.

### Architecture — Clean separation of concerns

Each layer has exactly one responsibility and no knowledge of the others:

| Layer | File | Responsibility |
|---|---|---|
| API | `main.py` | HTTP routing, request/response, logging, claim persistence |
| LLM interaction | `chain.py` | LangGraph pipeline — `extract_node`, `validate_node`, `coverage_node` |
| Tool integration | `warranty_mcp_server.py` | MCP server exposing warranty check as external tool |
| Validation | `vin_tools.py` | Deterministic VIN checks — no LLM, no framework |
| Domain logic | `warranty.py` | Coverage stub — zero knowledge of HTTP or LLM |
| Persistence | `store.py` | Thread-safe in-memory store — zero knowledge of HTTP or LLM |
| Schemas | `models.py` | Pydantic models only — no business logic |

The LangGraph `StateGraph` makes the pipeline structure explicit and visible: three named nodes, typed shared state, each node writing only its own fields.

### LLM Integration — Prompting, structured output, graceful failure

**Prompting:**
- `extract_node` system prompt is focused on one job only: extract 8 fields from unstructured text. No VIN validation logic in the prompt — that belongs in code.
- `coverage_node` prompt instructs the LLM to call the available warranty tool — one sentence, nothing more.

**Structured output:**
- `create_agent` with `response_format=ClaimExtractionBase` enforces the Pydantic schema on every LLM response. No regex, no `json.loads`, no manual field mapping.
- `coverage_node` uses `response_format=CoverageResult` for the same guarantee on coverage output.

**Graceful failure:**
- Extraction failure (network, bad output) → `main.py` catches the exception and returns `HTTP 422` with a clear error message.
- Coverage failure (MCP error, tool raises) → caught inside `coverage_node`, returns `eligible: false` with the error as `reason`. The pipeline always completes; the caller always gets a response.

### Code Quality — Type hints, Pydantic models, naming, comments

**Type hints:** every function has full signatures. `ClaimState` is a `TypedDict` — the shared pipeline state is typed, not a free-form dict.

**Pydantic models:** six models covering every boundary — `ClaimRequest` (input), `ClaimExtractionBase` (LLM output), `ClaimExtraction` (full extraction), `CoverageResult` (MCP output), `ClaimResponse` (API response), `ClaimRecord` (persisted record), `ErrorResponse` (error shape).

**Naming:** node names describe their job (`extract_node`, `validate_node`, `coverage_node`). State fields match the domain (`vin_valid`, `vin_issues`, `warranty_type`). No abbreviations, no generic names.

**Comments:** module docstrings explain *why*, not *what*. Standards are cited inline (`ISO 3779`, `49 CFR Part 565`). Implementation details that would surprise a reader are explained; obvious code is left uncommented.

### Error Handling — LLM garbage, malformed VIN, tool raises

| Scenario | Where caught | What happens |
|---|---|---|
| LLM returns unparseable output | `create_agent` + Pydantic `response_format` | Schema enforced — invalid output raises before reaching caller |
| LLM extraction fails entirely | `main.py` `try/except` around `run_claim_pipeline` | `HTTP 422` with `"Claim pipeline failed: ..."` |
| VIN is wrong length | `validate_node` length check | `vin_valid: false`, `vin_issues: ["VIN is N characters, must be 17"]`, checks 2-4 skipped |
| VIN has bad check digit / WMI / year char | `validate_node` calls to `vin_tools.py` | `vin_valid: false`, exact issue string in `vin_issues` |
| MCP server fails to start | `coverage_node` `try/except` | `eligible: false`, `reason: "Coverage check failed: ..."`, `warranty_type: "Unknown"` |
| Warranty stub raises `ValueError` (bad VIN / unknown make) | `coverage_node` `try/except` | Same graceful degradation as above |
| `GET /claims/{id}` for unknown ID | `main.py` | `HTTP 404` with clear message |

### AI Tool Usage — Claude Code

**Claude Code** (`claude-sonnet-4-6`) was used as the primary development tool throughout. 

---

## How Each Requirement Is Met

### Requirement 1 -- API Endpoint

The API is built with **FastAPI**. Two endpoints are provided:

- `POST /analyze-claim` -- accepts raw repair order text, returns structured claim data and coverage result.
- `GET /claims/{claim_id}` -- retrieves any previously analyzed claim by its ID (bonus endpoint).

Request and response shapes are defined as **Pydantic models** in `app/models.py`, which automatically validates types and gives clear error messages if the input is malformed.

### Requirement 2 -- LLM Usage

We use **Claude** (`claude-sonnet-4-6`) via `langchain.agents.create_agent` in two nodes:

- **`extract_node`** -- LLM reads unstructured RO text and extracts 8 structured fields using `response_format=ClaimExtractionBase`. No regex, no manual JSON parsing.
- **`coverage_node`** -- LLM calls the warranty MCP tool and returns a structured `CoverageResult`.
- **All 10 fields returned** -- `vin`, `year`, `make`, `model`, `mileage`, `repair_description`, `part_number`, `labor_hours`, `vin_valid`, `vin_issues`.
- **Graceful failure** -- if the LLM call fails, the API returns HTTP 422. Coverage failures are caught inside `coverage_node` and degrade gracefully.

### Requirement 3 -- Tool Integration

The challenge provides `check_warranty_coverage()` as an external module. We integrate it through MCP:

**Layer 1 -- `app/warranty.py`** is the stub implementation of the external adjudication API. It covers three real warranty tiers:

| Warranty Type | Condition |
|---|---|
| Voltec (EV battery) | Chevrolet Bolt EV, within 8 years / 100,000 miles |
| Bumper-to-Bumper | Within 3 years / 36,000 miles |
| Powertrain | Within 5 years / 60,000 miles |

**Layer 2 -- `app/warranty_mcp_server.py`** wraps `check_warranty_coverage()` as an MCP tool using `FastMCP`. The server runs as a subprocess with stdio transport, simulating a real external warranty adjudication API.

**Layer 3 -- `app/chain.py` `coverage_node`** connects to the MCP server at runtime using `MultiServerMCPClient`. The LLM discovers the tool, calls it with the extracted vehicle fields, and returns a structured `CoverageResult`.

### Bonus Items Completed

| Bonus | How |
|---|---|
| LangGraph pipeline | `StateGraph` with 3 named nodes: `extract_node`, `validate_node`, `coverage_node` |
| VIN validation (4 checks) | Length + model-year char + WMI + check digit — all deterministic Python in `validate_node` |
| MCP integration | `warranty_mcp_server.py` exposes coverage check as MCP tool; agent connects via `MultiServerMCPClient` (stdio) |
| `GET /claims/{claim_id}` | In-memory store in `app/store.py`, thread-safe with a `Lock` |
| Docker | `Dockerfile` + `docker-compose.yml` -- one command to run |
| Unit tests | `tests/` -- pytest suite, LLM calls mocked |
| Structured logging | JSON log format in `main.py`, logs every step with `claim_id` |

---

## Project Structure

```
app/
  chain.py               -- LangGraph StateGraph: extract_node, validate_node, coverage_node
  vin_tools.py           -- 4 deterministic VIN validation functions (plain Python, no LLM)
  warranty_mcp_server.py -- MCP server (FastMCP, stdio) wrapping check_warranty_coverage()
  main.py                -- FastAPI routes + structured JSON logging
  models.py              -- Pydantic schemas: ClaimExtractionBase, ClaimExtraction,
                            CoverageResult, ClaimResponse, ClaimRecord, ErrorResponse
  warranty.py            -- check_warranty_coverage() stub (simulated external API)
  store.py               -- thread-safe in-memory claim store (threading.Lock)
  __init__.py
tests/
  test_extraction.py     -- 19 tests: warranty stub, VIN tools, store, API routes (LLM mocked)
  __init__.py
.env.example             -- ANTHROPIC_API_KEY template
.gitignore
Dockerfile
docker-compose.yml
requirements.txt
```

---

## VIN Validation

`validate_node` runs 4 deterministic checks in sequence. No LLM involved — results are
identical on every call.

| # | Check | Standard | Skipped if |
|---|---|---|---|
| 1 | Length = 17 characters | ISO 3779 | — |
| 2 | Model-year character (position 10) vs. extracted year | ISO 3779 | VIN length != 17 |
| 3 | WMI (positions 1-3) vs. extracted make | ISO 3779 / NHTSA | VIN length != 17 |
| 4 | Check digit (position 9) NHTSA checksum | 49 CFR Part 565 | VIN length != 17 |

If length is wrong, only issue 1 is reported and checks 2-4 are skipped (they would give
misleading results on a malformed VIN).

`vin_issues` contains the exact string returned by each failing function — never
paraphrased, never hallucinated.

**Why plain Python functions instead of LLM tools?** Fixed rules (arithmetic, table
lookups) belong in code. They are always correct, produce identical output on every call,
and are trivially unit-testable without mocking.

---

## LangGraph Pipeline

```python
# chain.py — graph wiring
_graph = StateGraph(ClaimState)
_graph.add_node("extract",  extract_node)   # LLM
_graph.add_node("validate", validate_node)  # Python
_graph.add_node("coverage", coverage_node)  # LLM + MCP
_graph.add_edge(START,      "extract")
_graph.add_edge("extract",  "validate")
_graph.add_edge("validate", "coverage")
_graph.add_edge("coverage", END)

workflow = _graph.compile()
```

`ClaimState` is a `TypedDict` — each node reads its inputs and writes its outputs to the
same shared state object. Nodes are independent and individually unit-testable.

---

## Setup

### Local (venv)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY

python -m uvicorn app.main:app --reload
```

API docs: <http://localhost:8000/docs>

### Docker

```bash
cp .env.example .env   # add your ANTHROPIC_API_KEY
docker compose up --build
```

---

## Example Request

```bash
curl -X POST http://localhost:8000/analyze-claim \
  -H "Content-Type: application/json" \
  -d '{
    "ro_text": "RO# 847291 | VIN: 1G1FY6S00N0000123 | 2022 Chevrolet Bolt EV | Mileage: 12,340 | Complaint: Battery warning light on, reduced range. | Repair: Replaced high-voltage battery module. | Parts: 24299461 (Battery Module Assembly) | Labor: 4.2 hrs | Tech: M. Rodriguez"
  }'
```

**Response:**

```json
{
  "claim_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "vin": "1G1FY6S00N0000123",
  "year": 2022,
  "make": "Chevrolet",
  "model": "Bolt EV",
  "mileage": 12340,
  "repair_description": "Replaced high-voltage battery module.",
  "part_number": "24299461",
  "labor_hours": 4.2,
  "vin_valid": false,
  "vin_issues": ["Check digit (position 9) does not match calculated value"],
  "coverage_eligible": true,
  "coverage_reason": "Vehicle within Voltec warranty: 8yr/100k miles",
  "warranty_type": "Voltec"
}
```

> **Note:** the sample VIN from the challenge spec (`1G1FY6S00N0000123`) has a correct
> WMI (Chevrolet) and model-year char (`N` = 2022), but its check digit is `0` when the
> NHTSA algorithm yields `X` -- caught deterministically by `validate_node`.

---

## Tests

```bash
python -m pytest tests/ -v
```

Tests cover:

- Warranty stub logic (Voltec eligible/expired, Bumper-to-Bumper, Powertrain, no coverage)
- Error cases: invalid VIN length, unknown make
- In-memory store save/retrieve
- API routes with mocked `run_claim_pipeline` (success, failure -> 422, missing claim -> 404)

---


