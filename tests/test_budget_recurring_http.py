from datetime import date

def _signup_and_login(client, email="test@example.com", password="test12345"):
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200

def _create_category(client, name="Housing", icon="🏠"):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200

def test_recurring_monthly_budget_creates(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "��")

    r = client.post(
        "/budget",
        data={
            "budget_type": "expense",
            "category_id": "1",
            "subcategory_id": "",
            "amount_eur": "99.99",
            "currency": "EUR",

            # recurring fields
            "is_recurring": "on",
            "repeat_unit": "monthly",
            "repeat_interval": "1",
            "day_of_month": "1",
            "weekday": "",
            "start_date": "",
            "end_date": "",

            # one-time date should be empty
            "one_time_date": "",
            "note": "Rent",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "99.99 EUR" in r.text
    assert "recurring" in r.text.lower()
    assert "rent" in r.text.lower()

def test_recurring_missing_fields_shows_error(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    # Missing repeat_unit / repeat_interval / selector should fail via validate_budget()
    r = client.post(
        "/budget",
        data={
            "budget_type": "expense",
            "category_id": "1",
            "subcategory_id": "",
            "amount_eur": "10",
            "currency": "EUR",

            "is_recurring": "on",
            "repeat_unit": "",
            "repeat_interval": "",
            "day_of_month": "",
            "weekday": "",
            "start_date": "",
            "end_date": "",
            "one_time_date": "",
            "note": "",
        },
        follow_redirects=True,
    )
    assert r.status_code == 400
    # We just check it contains "requires" or "Recurring" to be robust against exact wording
    assert "recurr" in r.text.lower()
