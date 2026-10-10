"""Download real daily rainfall for Sri Lankan towns from the Open-Meteo archive API.

The simulator draws each project's weather from this history, so monsoon timing and intensity
come from real data rather than an invented distribution. The result is committed as
``rainfall.csv`` so training is reproducible offline; run this again only to refresh it.

    python -m data_generator.rainfall

Open-Meteo is free and needs no key. Only town coordinates are sent.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START, END = "2012-01-01", "2025-12-31"
OUTPUT = Path(__file__).with_name("rainfall.csv")

# Towns across the wet, intermediate and dry zones, so both monsoons are represented.
LOCATIONS: dict[str, tuple[float, float]] = {
    "colombo": (6.9271, 79.8612),  # wet zone, south-west monsoon (May to September)
    "kandy": (7.2906, 80.6337),  # central hills
    "galle": (6.0535, 80.2210),  # south coast, wet zone
    "ratnapura": (6.6828, 80.3992),  # wettest region
    "kurunegala": (7.4863, 80.3647),  # intermediate zone
    "jaffna": (9.6615, 80.0255),  # dry zone, north-east monsoon (October to January)
    "batticaloa": (7.7310, 81.6747),  # east coast, north-east monsoon
}


def fetch(latitude: float, longitude: float) -> list[tuple[str, float]]:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": START,
            "end_date": END,
            "daily": "precipitation_sum",
            "timezone": "Asia/Colombo",
        }
    )
    with urllib.request.urlopen(f"{ARCHIVE_URL}?{query}", timeout=60) as response:  # noqa: S310 (fixed https URL)
        payload = json.load(response)
    days = payload["daily"]["time"]
    rain = payload["daily"]["precipitation_sum"]
    return [(day, float(mm) if mm is not None else 0.0) for day, mm in zip(days, rain, strict=True)]


def main() -> int:
    rows: list[tuple[str, str, float]] = []
    for town, (lat, lon) in LOCATIONS.items():
        series = fetch(lat, lon)
        rows.extend((town, day, mm) for day, mm in series)
        yearly = sum(mm for _, mm in series) / (len(series) / 365.25)
        print(f"{town}: {len(series)} days, {yearly:.0f} mm a year")
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["town", "date", "rain_mm"])
        writer.writerows((town, day, f"{mm:.1f}") for town, day, mm in rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
