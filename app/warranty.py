"""
Stub implementation of the warranty coverage tool.

As per the challenge requirement:
  "You do NOT need to implement this function. Write a reasonable stub/mock
   that returns plausible results for testing. We want to see how you integrate
   with an external tool, not how you implement warranty logic."

In production this would be replaced by a call to a real warranty adjudication
service. This stub returns plausible results based on simple year/mileage rules
so the integration can be tested end-to-end.
"""

_KNOWN_MAKES = {
    "chevrolet", "gmc", "ford", "toyota", "honda",
    "nissan", "hyundai", "kia", "bmw", "mercedes-benz",
    "dodge", "jeep", "subaru", "mazda", "volkswagen",
}


def check_warranty_coverage(
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

    Returns:
        {
            "eligible": bool,
            "reason": str,
            "warranty_type": str  # "Voltec" | "Powertrain" | "Bumper-to-Bumper" | "None"
        }

    Raises:
        ValueError: If VIN format is invalid or make/model combination is unknown.
    """
    if not vin or len(vin) != 17:
        raise ValueError(f"Invalid VIN format: '{vin}' (must be 17 characters)")

    if make.strip().lower() not in _KNOWN_MAKES:
        raise ValueError(f"Unknown make/model combination: '{make}' / '{model}'")

    vehicle_age = 2025 - year

    # Voltec — GM EV battery warranty (industry standard: 8yr / 100k miles)
    if make.lower() == "chevrolet" and "bolt" in model.lower():
        if mileage <= 100_000 and vehicle_age <= 8:
            return {
                "eligible": True,
                "reason": "Vehicle within Voltec warranty: 8yr/100k miles",
                "warranty_type": "Voltec",
            }
        return {
            "eligible": False,
            "reason": "Vehicle outside Voltec warranty period (8yr/100k miles)",
            "warranty_type": "Voltec",
        }

    # Bumper-to-Bumper — industry standard: 3yr / 36k miles
    if vehicle_age <= 3 and mileage <= 36_000:
        return {
            "eligible": True,
            "reason": "Vehicle within Bumper-to-Bumper warranty: 3yr/36k miles",
            "warranty_type": "Bumper-to-Bumper",
        }

    # Powertrain — industry standard: 5yr / 60k miles
    if vehicle_age <= 5 and mileage <= 60_000:
        return {
            "eligible": True,
            "reason": "Vehicle within Powertrain warranty: 5yr/60k miles",
            "warranty_type": "Powertrain",
        }

    return {
        "eligible": False,
        "reason": "Vehicle outside all applicable warranty periods",
        "warranty_type": "None",
    }
