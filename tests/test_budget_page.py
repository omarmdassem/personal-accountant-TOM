from datetime import date

def _signup_and_login(client, email="test@example.com", password="test12345"):
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200

def _create_category(client, name="Housing", icon="🏠"):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200
    assert name in r.text

def test_create_one_time_budget_displays_euros(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    # Create a one-time expense budget item for 12.99 EUR
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
    assert "12.99 EUR" in r.text
    assert "Rent" in r.text

def test_budgets_redirects_to_budget(client):
    _signup_and_login(client)
    r = client.get("/budgets", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/budget"
