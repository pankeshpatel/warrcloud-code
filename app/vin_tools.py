"""
VIN validation functions — deterministic checks called directly by validate_node.

Standards:
  ISO 3779  — WMI and model-year character
              https://en.wikipedia.org/wiki/Vehicle_identification_number
  49 CFR Part 565 — check digit algorithm
              https://www.ecfr.gov/current/title-49/subtitle-B/chapter-V/part-565
"""

# ── Check 2 — Model-year character (ISO 3779) ─────────────────────────────────

_YEAR_CHAR: dict[str, list[int]] = {
    "A": [1980, 2010], "B": [1981, 2011], "C": [1982, 2012],
    "D": [1983, 2013], "E": [1984, 2014], "F": [1985, 2015],
    "G": [1986, 2016], "H": [1987, 2017], "J": [1988, 2018],
    "K": [1989, 2019], "L": [1990, 2020], "M": [1991, 2021],
    "N": [1992, 2022], "P": [1993, 2023], "R": [1994, 2024],
    "S": [1995, 2025], "T": [1996],       "V": [1997],
    "W": [1998],       "X": [1999],       "Y": [2000],
    "1": [2001], "2": [2002], "3": [2003], "4": [2004],
    "5": [2005], "6": [2006], "7": [2007], "8": [2008], "9": [2009],
}

# ── Check 3 — WMI vs. make (ISO 3779 / NHTSA) ────────────────────────────────

_WMI_MAKE: dict[str, str] = {
    "1G1": "Chevrolet", "1G2": "Pontiac", "1G4": "Buick",
    "1G6": "Cadillac",  "1GC": "Chevrolet", "1GT": "GMC",
    "1FA": "Ford", "1FB": "Ford", "1FC": "Ford",
    "1FD": "Ford", "1FM": "Ford", "1FT": "Ford",
    "1HG": "Honda", "2HG": "Honda",
    "1J4": "Jeep",
    "1N4": "Nissan", "1N6": "Nissan",
    "2T1": "Toyota", "JTD": "Toyota", "JTE": "Toyota",
    "JTJ": "Toyota", "JTM": "Toyota",
    "WAU": "Audi",
    "WBA": "BMW", "WBS": "BMW", "WBY": "BMW",
    "WDB": "Mercedes-Benz", "WDC": "Mercedes-Benz",
}

# ── Check 4 — Check digit (49 CFR Part 565) ──────────────────────────────────

_TRANSLITERATION: dict[str, int] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


# ── Validation functions ──────────────────────────────────────────────────────

def check_vin_model_year(vin: str, year: int) -> dict:
    """Check if position 10 of the VIN (model-year character) is consistent
    with the extracted year. Based on ISO 3779."""
    if len(vin) < 10:
        return {"pass": False, "issue": "VIN too short to read model-year character"}
    pos10 = vin[9].upper()
    valid_years = _YEAR_CHAR.get(pos10, [])
    if not valid_years:
        return {"pass": False, "issue": f"Model-year character '{pos10}' (position 10) is not a valid encoding"}
    if year in valid_years:
        return {"pass": True, "issue": None}
    return {
        "pass": False,
        "issue": f"Model-year character '{pos10}' (position 10) encodes {valid_years}, not {year}",
    }


def check_vin_wmi(vin: str, make: str) -> dict:
    """Check if positions 1-3 of the VIN (WMI) are consistent with the
    extracted make. Based on ISO 3779 / NHTSA WMI assignments."""
    if len(vin) < 3:
        return {"pass": False, "issue": "VIN too short to read WMI"}
    wmi = vin[:3].upper()
    expected = _WMI_MAKE.get(wmi)
    if expected is None:
        return {"pass": True, "issue": None}  # unknown WMI — cannot verify
    if expected.lower() == make.strip().lower():
        return {"pass": True, "issue": None}
    return {
        "pass": False,
        "issue": f"WMI '{wmi}' (positions 1-3) is assigned to {expected}, not {make}",
    }


def check_vin_checkdigit(vin: str) -> dict:
    """Verify the check digit at position 9 of the VIN using the NHTSA
    checksum algorithm. Based on 49 CFR Part 565."""
    if len(vin) != 17:
        return {"pass": False, "issue": "Cannot verify check digit: VIN is not 17 characters"}
    vin = vin.upper()
    total = 0
    for i, ch in enumerate(vin):
        if i == 8:
            continue
        val = int(ch) if ch.isdigit() else _TRANSLITERATION.get(ch)
        if val is None:
            return {"pass": False, "issue": f"Cannot verify check digit: invalid character '{ch}' at position {i + 1}"}
        total += val * _WEIGHTS[i]
    remainder = total % 11
    expected = "X" if remainder == 10 else str(remainder)
    actual = vin[8]
    if actual == expected:
        return {"pass": True, "issue": None}
    return {
        "pass": False,
        "issue": "Check digit (position 9) does not match calculated value",
    }
