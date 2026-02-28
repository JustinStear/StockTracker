from __future__ import annotations

import math
from dataclasses import dataclass

import requests

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_MILES * c


class GeocoderError(RuntimeError):
    pass


@dataclass(slots=True)
class ZipGeocoder:
    timeout_seconds: float = 10.0

    def geocode_zip(self, zip_code: str) -> tuple[float, float]:
        url = f"https://api.zippopotam.us/us/{zip_code}"
        response = requests.get(url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise GeocoderError(f"zip lookup failed: {response.status_code}")

        payload = response.json()
        places = payload.get("places") or []
        if not places:
            raise GeocoderError(f"no places found for zip {zip_code}")

        place = places[0]
        try:
            lat = float(place["latitude"])
            lon = float(place["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocoderError("invalid geocoder response") from exc

        return lat, lon
