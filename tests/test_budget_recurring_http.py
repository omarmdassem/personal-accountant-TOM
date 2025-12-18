import re
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


def test_recurring_monthly_budget_creates(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    r = client.post(
        "/budget",
        data={
            "budget_type": "expense",
            "category_id": "1",
            "subcategory_id": "",
            "amount_eur": "99.99",
            "currency": "EUR",
            "is_recurring": "on",
            "repeat_unit": "monthly",
            "repeat_interval": "1",
            "day_of_month": "1",
            "weekday": "",
            "start_date": "",
            "end_date": "",
            "one_time_date": "",
            "note": "Rent",
        },
        follow_redirects=True,
    )

    assert r.status_code == 200
    _assert_money_rendered(r.text, "99.99")
