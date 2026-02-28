from stockcheck.geo import haversine_miles


def test_haversine_zero_distance() -> None:
    assert haversine_miles(40.0, -88.0, 40.0, -88.0) == 0.0


def test_haversine_known_distance_approx() -> None:
    # Chicago to New York is roughly 711 miles.
    dist = haversine_miles(41.8781, -87.6298, 40.7128, -74.0060)
    assert 680 <= dist <= 740
