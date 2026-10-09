#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone

from gb_power_market.v27_validation_maturity import assess_validation_maturity


def main() -> None:
    result = assess_validation_maturity(datetime.now(timezone.utc))
    print(json.dumps(result, indent=2))
    if not result["sealed_validation_mature"]:
        raise SystemExit(
            "SEALED_VALIDATION_NOT_MATURE: no Elexon/NESO validation download is permitted yet"
        )


if __name__ == "__main__":
    main()
