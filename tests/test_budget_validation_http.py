from datetime import date

def _signup_and_login(client, email="test@example.com", password="test12345"):
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200

def _create_category(client, name="Housing", icon="🏠"):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200

def test_missing_category_shows_nice_error(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    # category_id intentionally missing/empty
    r = client.post(
        "/budget",
        data={
            "budget_type": "expense",
            "category_id": "",
            "subcategory_id": "",
            "amount_eur": "10",
            "currency": "EUR",
            "one_time_date": str(date(2025, 1, 1)),
            "note": "",
        },
        follow_redirects=True,
    )
    assert r.status_code == 400
    assert "category is required" in r.text.lower()
