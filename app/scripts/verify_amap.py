"""Manual real-API smoke test.  Never prints the Amap key."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
os.environ.setdefault("CONFIG_PATH", str(APP / "config.yaml"))

from dotenv import load_dotenv

load_dotenv(APP / ".env")

from travel_agent.services.amap_client import (  # noqa: E402
    AmapNotConfigured,
    AmapServiceError,
)
from travel_agent.services.amap_place_search import (  # noqa: E402
    amap_geocode,
    amap_poi_search,
    amap_regeocode,
)
from travel_agent.services.global_route_search import global_route_search  # noqa: E402


async def main() -> int:
    try:
        poi = await amap_poi_search(keywords="雷峰塔", city="杭州", limit=3)
        print("POI", poi["count"], [place["name"] for place in poi["places"]])
        if not poi["places"]:
            print("POI no_result")
            return 1
        start = poi["places"][0]

        target = await amap_poi_search(keywords="灵隐寺", city="杭州", limit=3)
        if not target["places"]:
            print("TARGET no_result")
            return 1
        end = target["places"][0]
        print("TARGET", end["name"], end["place_id"])

        geo = await amap_geocode(address="杭州市西湖区雷峰塔", city="杭州")
        print("GEO", geo["count"], geo["places"][0]["level"] if geo["places"] else "no_result")
        regeo = await amap_regeocode(
            latitude=start["latitude"], longitude=start["longitude"]
        )
        print("REGEO", regeo["result"]["address"])

        departure = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        for mode in ("walk", "public_transit"):
            route = await global_route_search(
                from_name=start["name"],
                from_place_id=start["place_id"],
                from_latitude=start["latitude"],
                from_longitude=start["longitude"],
                to_name=end["name"],
                to_place_id=end["place_id"],
                to_latitude=end["latitude"],
                to_longitude=end["longitude"],
                departure_time=departure.isoformat(),
                mode=mode,
            )
            first = route["routes"][0]
            print(
                "ROUTE",
                mode,
                route.get("provider"),
                first.get("distance_meters"),
                first.get("duration_minutes"),
                first.get("total_cost_cny"),
                first.get("fare_type"),
            )
        return 0
    except AmapNotConfigured as exc:
        print("NOT_CONFIGURED", str(exc))
        return 2
    except AmapServiceError as exc:
        print("AMAP_ERROR", exc.code, str(exc))
        return 3
    except Exception as exc:
        print("ERROR", type(exc).__name__, str(exc))
        return 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
