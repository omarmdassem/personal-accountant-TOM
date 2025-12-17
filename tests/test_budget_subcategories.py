def _signup_and_login(client, email="test@example.com", password="test12345"):
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200

def _create_category(client, name="Housing", icon="🏠"):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200

def _create_subcategory(client, category_id=1, name="Rent", icon="🏡"):
    r = client.post(f"/categories/{category_id}/subcategories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200

def test_budget_subcategories_endpoint_returns_options(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")
    _create_subcategory(client, 1, "Rent", "🏡")

    r = client.get("/budget/subcategories?category_id=1")
    assert r.status_code == 200
    assert "(none)" in r.text
    assert "Rent" in r.text
