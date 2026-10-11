"""Write the rain climate table the backend uses for ``wet_days_ahead``.

    python -m data_generator.climate

For each of the seven towns in ``rainfall.csv``: its coordinates and the share of days with heavy
rain (10 mm or more, BR-06) in each calendar month, over 2012 to 2025. The simulator computes the
same numbers (``simulate.heavy_rain_climate``); a test checks the backend's copy matches. A site
uses the nearest town's climate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from data_generator.rainfall import END, LOCATIONS, START
from data_generator.simulate import HEAVY_RAIN_MM, heavy_rain_climate, load_rainfall

OUTPUT = Path(__file__).parents[2] / "backend" / "app" / "ai" / "risk" / "rain_climate.json"


def table() -> dict[str, object]:
    rainfall = load_rainfall()
    return {
        "source": f"Open-Meteo archive, daily precipitation {START} to {END} (data_generator/rainfall.csv)",
        "heavy_rain_mm": HEAVY_RAIN_MM,
        "towns": {
            town: {
                "latitude": LOCATIONS[town][0],
                "longitude": LOCATIONS[town][1],
                "heavy_day_share_by_month": [heavy_rain_climate(rainfall[town])[m] for m in range(1, 13)],
            }
            for town in sorted(rainfall)
        },
    }


def main() -> int:
    OUTPUT.write_text(json.dumps(table(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
