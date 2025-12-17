def _signup_and_login(client, email="test@example.com", password="test12345"):
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200

def _create_category(client, name="Housing", icon="🏠"):
    r = client.post("/categories", data={"name": name, "icon": icon}, follow_redirects=True)
    assert r.status_code == 200

def test_create_subcategory_persists(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    r = client.post("/categories/1/subcategories", data={"name": "Rent", "icon": "🏡"}, follow_redirects=True)
    assert r.status_code == 200
    assert "Rent" in r.text
    assert "🏡" in r.text

def test_duplicate_subcategory_shows_error(client):
    _signup_and_login(client)
    _create_category(client, "Housing", "🏠")

    r1 = client.post("/categories/1/subcategories", data={"name": "Rent", "icon": "🏡"}, follow_redirects=True)
    assert r1.status_code == 200

    r2 = client.post("/categories/1/subcategories", data={"name": "Rent", "icon": "🏡"}, follow_redirects=True)
    assert r2.status_code == 400
    assert "already exists" in r2.text.lower()
