import re
import textwrap
from uuid import uuid4

from sqlmodel import Session, select

from app.models import Budget, User


def _signup_and_login(client, password="secret123"):
    email = f"test-{uuid4().hex}@example.com"

    r = client.post("/signup", data={"email": email, "password": password}, follow_redirects=True)
    assert r.status_code in (200, 303)

    r2 = client.post("/login", data={"email": email, "password": password}, follow_redirects=True)
    assert r2.status_code == 200
    return email


def _upload_csv_and_get_review(client, csv_text: str):
    r0 = client.get("/budget/import")
    assert r0.status_code == 200

    # IMPORTANT: remove indentation + ensure newline at end
    csv_text = textwrap.dedent(csv_text).lstrip()
    if not csv_text.endswith("\n"):
        csv_text += "\n"

    r = client.post(
        "/budget/import",
        files={"file": ("budget.csv", csv_text.encode("utf-8"), "text/csv")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Review Import" in r.text
    return r


def _apply_import_action(client, action: str):
    r = client.post("/budget/import/apply", data={"action": action}, follow_redirects=True)
    assert r.status_code == 200
    return r


def _extract_metric_value(html: str, label: str) -> int:
    # Prefer extracting from the same <tr> row.
    row_pat = rf"""
        <tr[^>]*>.*?
          <t[dh][^>]*>\s*{re.escape(label)}\s*</t[dh]>\s*
          <t[dh][^>]*>\s*(\d+)\s*</t[dh].*?
        </tr>
    """
    m = re.search(row_pat, html, flags=re.IGNORECASE | re.DOTALL | re.VERBOSE)
    if m:
        return int(m.group(1))

    # Fallback: first number AFTER the label.
    idx = html.lower().find(label.lower())
    assert idx != -1, f"Could not find metric label '{label}' in HTML."
    window_after = html[idx : idx + 1200]
    m2 = re.search(r"(\d+)", window_after)
    assert m2, f"Could not find a number after metric label '{label}'."
    return int(m2.group(1))


def _get_uid_by_email(engine, email: str) -> int:
    with Session(engine) as db:
        u = db.exec(select(User).where(User.email == email)).first()
        assert u is not None, f"Could not find user in DB for email={email}"
        return int(u.id)


def _debug_notes_for_user(engine, uid: int) -> list[str]:
    with Session(engine) as db:
        rows = db.exec(select(Budget.note).where(Budget.user_id == uid)).all()
        # rows may contain None
        return [r if r is not None else "None" for r in rows]


def _count_budgets_with_note_contains(engine, uid: int, needle: str) -> int:
    with Session(engine) as db:
        rows = db.exec(
            select(Budget).where(Budget.user_id == uid, Budget.note.contains(needle))
        ).all()
        return len(rows)


def test_budget_csv_import_keep_vs_replace_duplicates(client, engine):
    # Clear leftover in-memory batch (safe no-op)
    try:
        from app.routes import budgets as budgets_routes
        budgets_routes._IMPORT_BATCHES.clear()
    except Exception:
        pass

    email = _signup_and_login(client)
    uid = _get_uid_by_email(engine, email)

    suffix = uuid4().hex[:8]
    cat1 = f"Housing-{suffix}"
    sub1 = f"Rent-{suffix}"
    cat2 = f"Insurance-{suffix}"

    note1 = f"Monthly rent {suffix}"
    note2 = f"Car insurance {suffix}"

    csv_text = f"""
type,category,subcategory,amount,currency,schedule,date,repeat_every,repeat_unit,on_weekday,on_day,start_date,end_date,note
expense,{cat1},{sub1},900.00,EUR,recurring,,1,month,,1,2025-01-01,,{note1}
expense,{cat2},,120.50,EUR,one-time,2025-02-01,,,,,,{note2}
"""

    # 1) First upload
    review1 = _upload_csv_and_get_review(client, csv_text)
    assert _extract_metric_value(review1.text, "Valid rows") == 2
    assert _extract_metric_value(review1.text, "Duplicates vs existing") == 0

    _apply_import_action(client, "keep")

    # Verify via DB (robust against whitespace)
    c1 = _count_budgets_with_note_contains(engine, uid, note1)
    c2 = _count_budgets_with_note_contains(engine, uid, note2)
    if c2 != 1:
        # give yourself useful debug output when it fails
        notes = _debug_notes_for_user(engine, uid)
        raise AssertionError(
            f"Expected 1 budget containing note2='{note2}', got {c2}. "
            f"All notes for uid={uid}: {notes}"
        )
    assert c1 == 1

    # 2) Upload same CSV again => duplicates detected (2)
    review2 = _upload_csv_and_get_review(client, csv_text)
    assert _extract_metric_value(review2.text, "Valid rows") == 2
    assert _extract_metric_value(review2.text, "Duplicates vs existing") == 2

    _apply_import_action(client, "keep")
    assert _count_budgets_with_note_contains(engine, uid, note1) == 2
    assert _count_budgets_with_note_contains(engine, uid, note2) == 2

    # 3) Upload again => still duplicates=2
    review3 = _upload_csv_and_get_review(client, csv_text)
    assert _extract_metric_value(review3.text, "Duplicates vs existing") == 2

    _apply_import_action(client, "replace")
    assert _count_budgets_with_note_contains(engine, uid, note1) == 1
    assert _count_budgets_with_note_contains(engine, uid, note2) == 1
