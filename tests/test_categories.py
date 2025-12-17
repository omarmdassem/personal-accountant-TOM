def _signup_and_login(client, email="test@example.com", password="test12345"):
    # create account (this also logs in via session cookie)
    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code == 200
    return r

def test_create_category_persists(client):
    _signup_and_login(client)

    # create a category
    r = client.post("/categories", data={"name": "Housing", "icon": "🏠"}, follow_redirects=True)
    assert r.status_code == 200

    # should show up in list page
    r2 = client.get("/categories")
    assert r2.status_code == 200
    assert "Housing" in r2.text
    assert "🏠" in r2.text

def test_duplicate_category_name_shows_error(client):
    _signup_and_login(client)

    r1 = client.post("/categories", data={"name": "Food", "icon": "🍔"}, follow_redirects=True)
    assert r1.status_code == 200

    r2 = client.post("/categories", data={"name": "Food", "icon": "🍔"}, follow_redirects=True)
    assert r2.status_code == 400
    assert "already exists" in r2.text.lower()
