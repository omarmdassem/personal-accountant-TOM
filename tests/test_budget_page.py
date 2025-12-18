import re
from datetime import date
from uuid import uuid4


def _signup_and_login(client, password="secret123"):
    email = f"test-{uuid4().hex}@example.com"
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code in (200, 303)
    r2 = client.post("/login", data={"email": email, "password": password}, follow_redirects=True)
    assert r2.status_code == 200
    return email


def _create_category(client, name: str, icon: str):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200


def _assert_money_rendered(html: str, amount: str):
    # Accept common EU/US formatting + EUR/€
    # amount like "12.99"
    if "." in amount:
        euros, cents = amount.split(".", 1)
    elif "," in amount:
        euros, cents = amount.split(",", 1)
    else:
        euros, cents = amount, "00"
    cents = (cents + "00")[:2]

    dot = f"{euros}.{cents}"
    comma = f"{euros},{cents}"

    patterns = [
        rf"{re.escape(dot)}\s*EUR",
        rf"{re.escape(comma)}\s*EUR",
        rf"EUR\s*{re.escape(dot)}",
        rf"EUR\s*{re.escape(comma)}",
        rf"€\s*{re.escape(dot)}",
        rf"€\s*{re.escape(comma)}",
        rf"{re.escape(dot)}\s*€",
        rf"{re.escape(comma)}\s*€",
    ]
    assert any(re.search(p, html) for p in patterns), "Amount not found in HTML in any supported format."


def test_create_one_time_budget_displays_euros(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    r = client.post(
        "/budget",
        data={
            "budget_type": "expense",
            "category_id": "1",
            "amount_eur": "12.99",
            "currency": "EUR",
            "one_time_date": str(date(2025, 1, 1)),
            "note": "Rent",
        },
        follow_redirects=True,
    )

    assert r.status_code == 200
    _assert_money_rendered(r.text, "12.99")
