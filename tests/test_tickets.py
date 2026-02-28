from stockcheck.tickets import TicketResult, TicketSearchService


def test_ticket_search_sorts_by_known_min_price(monkeypatch) -> None:
    svc = TicketSearchService()
    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")

    def fake_tm(*args, **kwargs):
        del args, kwargs
        return [
            TicketResult(
                source="ticketmaster",
                event_name="Event B",
                venue="V",
                event_date="2026-03-02",
                city="X",
                min_price=120.0,
                max_price=150.0,
                currency="USD",
                url="https://example.com/b",
                availability="available",
            ),
            TicketResult(
                source="ticketmaster",
                event_name="Event A",
                venue="V",
                event_date="2026-03-01",
                city="X",
                min_price=80.0,
                max_price=90.0,
                currency="USD",
                url="https://example.com/a",
                availability="available",
            ),
        ]

    monkeypatch.setattr(svc, "_search_ticketmaster", fake_tm)

    result = svc.search(
        query="test",
        zip_code="21032",
        radius_miles=50,
        date_from=None,
        date_to=None,
        event_id=None,
        section_query=None,
        max_price=None,
        include_ticketmaster=True,
        include_seatgeek=False,
        include_stubhub=False,
        include_vividseats=False,
        include_tickpick=False,
        limit=10,
    )

    assert [r.event_name for r in result.results] == ["Event A", "Event B"]


def test_ticket_search_generates_stubhub_link() -> None:
    svc = TicketSearchService()
    svc._choose_best_link = lambda source, query, primary_url: primary_url  # type: ignore[method-assign]
    result = svc.search(
        query="metallica",
        zip_code="21032",
        radius_miles=50,
        date_from=None,
        date_to=None,
        event_id=None,
        section_query=None,
        max_price=None,
        include_ticketmaster=False,
        include_seatgeek=False,
        include_stubhub=True,
        include_vividseats=False,
        include_tickpick=False,
        limit=10,
    )

    assert len(result.results) == 1
    assert result.results[0].source == "stubhub"
    assert "stubhub.com" in result.results[0].url


def test_ticket_search_section_and_max_price_filters() -> None:
    svc = TicketSearchService()
    svc._choose_best_link = lambda source, query, primary_url: primary_url  # type: ignore[method-assign]
    rows = [
        TicketResult(
            source="stubhub",
            event_name="Artist Live Floor Seats",
            venue="Arena",
            event_date="2026-05-01",
            city="X",
            min_price=250.0,
            max_price=300.0,
            currency="USD",
            url="https://stubhub.com/a",
            availability="available",
        ),
        TicketResult(
            source="stubhub",
            event_name="Artist Live Section 102",
            venue="Arena",
            event_date="2026-05-01",
            city="X",
            min_price=120.0,
            max_price=180.0,
            currency="USD",
            url="https://stubhub.com/b",
            availability="available",
        ),
    ]

    def fake_public(*args, **kwargs):
        del args, kwargs
        return rows

    # Assign directly to keep this unit test simple and deterministic.
    svc._search_public_provider = fake_public  # type: ignore[method-assign]

    result = svc.search(
        query="artist",
        zip_code="21032",
        radius_miles=50,
        date_from=None,
        date_to=None,
        event_id=None,
        section_query="102",
        max_price=200,
        include_ticketmaster=False,
        include_seatgeek=False,
        include_stubhub=True,
        include_vividseats=False,
        include_tickpick=False,
        limit=10,
    )

    assert len(result.results) == 1
    assert "102" in result.results[0].event_name
