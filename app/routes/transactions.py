from __future__ import annotations

import csv
import io
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user_id
from ..models import Category, Subcategory, Transaction
from ..domain import BudgetType
from ..money import MoneyParseError, cents_to_euros_str, euros_to_cents

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# NOTE: early-stage in-memory store for import batches (good for dev/tests).
# In production, you'd move this to DB / Redis / filesystem.
_TX_IMPORT_BATCHES: dict[str, dict] = {}


def _load_transaction_page_data(db: Session, uid: int):
    categories = db.exec(
        select(Category).where(Category.user_id == uid).order_by(Category.name)
    ).all()

    subcategories = db.exec(
        select(Subcategory).where(Subcategory.user_id == uid).order_by(Subcategory.name)
    ).all()

    # Prefer created_at if your Transaction model has it; fallback to date/id.
    try:
        transactions = db.exec(
            select(Transaction)
            .where(Transaction.user_id == uid)
            .order_by(Transaction.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    except Exception:
        transactions = db.exec(
            select(Transaction)
            .where(Transaction.user_id == uid)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
        ).all()

    categories_by_id = {c.id: c for c in categories}
    subcategories_by_id = {s.id: s for s in subcategories}

    return categories, transactions, categories_by_id, subcategories_by_id


def _render_transaction_page(
    request: Request,
    uid: int,
    db: Session,
    error: str | None = None,
    status_code: int = 200,
):
    categories, transactions, categories_by_id, subcategories_by_id = _load_transaction_page_data(db, uid)

    return templates.TemplateResponse(
        "transactions.html",
        {
            "request": request,
            "title": "Transactions",
            "user_id": uid,
            "categories": categories,
            "transactions": transactions,
            "categories_by_id": categories_by_id,
            "subcategories_by_id": subcategories_by_id,
            "error": error,
            "cents_to_euros_str": cents_to_euros_str,
        },
        status_code=status_code,
    )


def _ensure_category(db: Session, uid: int, name: str) -> Category:
    name = (name or "").strip()
    existing = db.exec(
        select(Category).where(Category.user_id == uid, Category.name == name)
    ).first()
    if existing:
        return existing
    c = Category(user_id=uid, name=name, icon=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _ensure_subcategory(db: Session, uid: int, category_id: int, name: str) -> Subcategory:
    name = (name or "").strip()
    existing = db.exec(
        select(Subcategory).where(
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
            Subcategory.name == name,
        )
    ).first()
    if existing:
        return existing
    s = Subcategory(user_id=uid, category_id=category_id, name=name, icon=None)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _parse_date(s: str) -> date:
    s = (s or "").strip()
    if not s:
        raise ValueError("date is required (YYYY-MM-DD).")
    return date.fromisoformat(s)


def _sig_from_row(row: dict) -> tuple:
    """
    Signature used for duplicate detection (ignores note).
    Includes description because two transactions same day/category but different purpose should not be treated as dup.
    """
    return (
        row["date"],
        row["type"],
        row["category"].strip().lower(),
        (row.get("subcategory") or "").strip().lower() or None,
        (row.get("description") or "").strip().lower(),
        row["amount_cents"],
        row["currency"].upper(),
    )


def _sig_from_existing(t: Transaction, cat_name: str, sub_name: str | None) -> tuple:
    ttype = t.type.value if hasattr(t.type, "value") else str(t.type)
    return (
        t.date,
        ttype,
        cat_name.strip().lower(),
        sub_name.strip().lower() if sub_name else None,
        (t.description or "").strip().lower(),
        t.amount_cents,
        (t.currency or "EUR").upper(),
    )


def _parse_csv(file_bytes: bytes) -> tuple[list[dict], list[dict]]:
    """
    Returns: (valid_rows, invalid_rows)
    invalid_rows entries: {"rownum": int, "error": str, "raw": dict}
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    buf = io.StringIO(text)

    # try to detect delimiter
    sample = text[:2048]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
        delimiter = dialect.delimiter
    except Exception:
        pass

    reader = csv.DictReader(buf, delimiter=delimiter)
    if not reader.fieldnames:
        return [], [{"rownum": 0, "error": "CSV has no header row.", "raw": {}}]

    reader.fieldnames = [h.strip() for h in reader.fieldnames]

    required = {"date", "type", "category", "amount", "currency"}
    missing = required - set(h.lower() for h in reader.fieldnames)
    if missing:
        return [], [{"rownum": 0, "error": f"Missing required columns: {', '.join(sorted(missing))}", "raw": {}}]

    valid: list[dict] = []
    invalid: list[dict] = []

    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}

        try:
            dt = _parse_date(row.get("date", ""))

            ttype = row.get("type", "").lower()
            if ttype not in ("income", "expense"):
                raise ValueError("type must be 'income' or 'expense'.")

            category = (row.get("category") or "").strip()
            if not category:
                raise ValueError("category is required.")

            subcategory = (row.get("subcategory") or "").strip() or None

            description = (row.get("description") or "").strip() or None

            amount_cents = euros_to_cents(row.get("amount", ""))

            currency = (row.get("currency") or "EUR").strip().upper() or "EUR"

            note = (row.get("note") or "").strip() or None

            valid.append(
                {
                    "date": dt,
                    "type": ttype,
                    "category": category,
                    "subcategory": subcategory,
                    "description": description,
                    "amount_cents": amount_cents,
                    "currency": currency,
                    "note": note,
                }
            )

        except MoneyParseError as e:
            invalid.append({"rownum": i, "error": str(e), "raw": row})
        except Exception as e:
            invalid.append({"rownum": i, "error": str(e), "raw": row})

    return valid, invalid


@router.get("/transactions")
def transactions_redirect():
    return RedirectResponse(url="/transaction", status_code=303)


@router.get("/transaction", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)
    return _render_transaction_page(request, uid, db)


@router.get("/transaction/subcategories", response_class=HTMLResponse)
def transaction_subcategories(
    request: Request,
    category_id: int | None = None,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return HTMLResponse("", status_code=401)

    if not category_id:
        return HTMLResponse('<option value="">(none)</option>', status_code=200)

    cat = db.exec(select(Category).where(Category.id == category_id, Category.user_id == uid)).first()
    if not cat:
        return HTMLResponse('<option value="">(none)</option>', status_code=200)

    subs = db.exec(
        select(Subcategory)
        .where(Subcategory.user_id == uid, Subcategory.category_id == category_id)
        .order_by(Subcategory.name)
    ).all()

    options = ['<option value="">(none)</option>']
    for s in subs:
        label = f"{s.icon or ''} {s.name}".strip()
        options.append(f'<option value="{s.id}">{label}</option>')
    return HTMLResponse("\n".join(options), status_code=200)


@router.post("/transaction")
def create_transaction(
    request: Request,
    tx_date: date | None = Form(None),
    tx_type: BudgetType = Form(...),

    category_id: str = Form(""),
    subcategory_id: str = Form(""),

    description: str = Form(""),
    amount_eur: str = Form(...),
    currency: str = Form("EUR"),
    note: str = Form(""),

    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    if tx_date is None:
        return _render_transaction_page(request, uid, db, error="Date is required.", status_code=400)

    if not category_id.strip():
        return _render_transaction_page(request, uid, db, error="Category is required.", status_code=400)

    try:
        category_id_int = int(category_id)
    except ValueError:
        return _render_transaction_page(request, uid, db, error="Invalid category.", status_code=400)

    cat = db.exec(
        select(Category).where(Category.id == category_id_int, Category.user_id == uid)
    ).first()
    if not cat:
        return _render_transaction_page(request, uid, db, error="Invalid category.", status_code=400)

    sub_id: int | None = None
    if subcategory_id.strip():
        try:
            sub_id = int(subcategory_id)
        except ValueError:
            return _render_transaction_page(request, uid, db, error="Invalid subcategory.", status_code=400)

        sub = db.exec(
            select(Subcategory).where(
                Subcategory.id == sub_id,
                Subcategory.user_id == uid,
                Subcategory.category_id == category_id_int,
            )
        ).first()
        if not sub:
            return _render_transaction_page(
                request, uid, db, error="Invalid subcategory for selected category.", status_code=400
            )

    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        return _render_transaction_page(request, uid, db, error=str(e), status_code=400)

    t = Transaction(
        user_id=uid,
        date=tx_date,
        type=tx_type,
        category_id=category_id_int,
        subcategory_id=sub_id,
        description=(description.strip() or None),
        amount_cents=amount_cents,
        currency=currency.strip().upper() or "EUR",
        note=(note.strip() or None),
    )

    db.add(t)
    db.commit()

    return RedirectResponse(url="/transaction", status_code=303)


@router.get("/transaction/template.csv")
def download_transaction_template(
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    header = [
        "date",
        "type",
        "category",
        "subcategory",
        "description",
        "amount",
        "currency",
        "note",
    ]
    example_rows = [
        ["2025-02-01", "expense", "Housing", "Rent", "Monthly rent", "900.00", "EUR", ""],
        ["2025-02-02", "expense", "Insurance", "", "Car insurance", "120.50", "EUR", ""],
    ]

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for r in example_rows:
        w.writerow(r)

    content = out.getvalue().encode("utf-8")
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transaction_template.csv"'},
    )


@router.get("/transaction/import", response_class=HTMLResponse)
def import_transaction_form(
    request: Request,
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "transaction_import.html",
        {"request": request, "title": "Import Transactions CSV", "user_id": uid, "error": None},
    )


@router.post("/transaction/import")
async def import_transaction_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    if not file.filename.lower().endswith(".csv"):
        return templates.TemplateResponse(
            "transaction_import.html",
            {
                "request": request,
                "title": "Import Transactions CSV",
                "user_id": uid,
                "error": "Please upload a .csv file.",
            },
            status_code=400,
        )

    data = await file.read()
    valid_rows, invalid_rows = _parse_csv(data)

    # existing signatures (by category/subcategory names)
    cats = db.exec(select(Category).where(Category.user_id == uid)).all()
    subs = db.exec(select(Subcategory).where(Subcategory.user_id == uid)).all()
    cat_by_id = {c.id: c.name for c in cats}
    sub_by_id = {s.id: (s.name, s.category_id) for s in subs}

    existing = db.exec(select(Transaction).where(Transaction.user_id == uid)).all()
    existing_sigs: dict[tuple, list[int]] = {}
    for t in existing:
        cat_name = cat_by_id.get(t.category_id, f"#{t.category_id}")
        sub_name = None
        if t.subcategory_id:
            sub_name = sub_by_id.get(t.subcategory_id, (None, None))[0]
        sig = _sig_from_existing(t, cat_name, sub_name)
        existing_sigs.setdefault(sig, []).append(t.id)

    duplicates = []
    for idx, r in enumerate(valid_rows):
        sig = _sig_from_row(r)
        if sig in existing_sigs:
            duplicates.append(idx)

    batch_id = str(uuid4())
    _TX_IMPORT_BATCHES[batch_id] = {
        "uid": uid,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "duplicates_idx": duplicates,
        "existing_sigs": existing_sigs,
    }

    request.session["transaction_import_batch_id"] = batch_id
    return RedirectResponse(url="/transaction/import/review", status_code=303)


@router.get("/transaction/import/review", response_class=HTMLResponse)
def import_transaction_review(
    request: Request,
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    batch_id = request.session.get("transaction_import_batch_id")
    batch = _TX_IMPORT_BATCHES.get(batch_id) if batch_id else None
    if not batch or batch.get("uid") != uid:
        return RedirectResponse(url="/transaction/import", status_code=303)

    valid_rows = batch["valid_rows"]
    invalid_rows = batch["invalid_rows"]
    duplicates_idx = set(batch["duplicates_idx"])

    preview = []
    for i, r in enumerate(valid_rows[:25]):
        preview.append({"row": r, "is_duplicate": i in duplicates_idx})

    return templates.TemplateResponse(
        "transaction_import_review.html",
        {
            "request": request,
            "title": "Review Import",
            "user_id": uid,
            "valid_count": len(valid_rows),
            "invalid_count": len(invalid_rows),
            "dup_count": len(duplicates_idx),
            "invalid_rows": invalid_rows,
            "preview_rows": preview,
            "cents_to_euros_str": cents_to_euros_str,
        },
    )


@router.post("/transaction/import/apply")
def import_transaction_apply(
    request: Request,
    action: str = Form(...),  # "keep" or "replace"
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    batch_id = request.session.get("transaction_import_batch_id")
    batch = _TX_IMPORT_BATCHES.get(batch_id) if batch_id else None
    if not batch or batch.get("uid") != uid:
        return RedirectResponse(url="/transaction/import", status_code=303)

    valid_rows: list[dict] = batch["valid_rows"]
    existing_sigs: dict[tuple, list[int]] = batch["existing_sigs"]

    if action not in ("keep", "replace"):
        return RedirectResponse(url="/transaction/import/review", status_code=303)

    if action == "replace":
        ids_to_delete: set[int] = set()
        for r in valid_rows:
            sig = _sig_from_row(r)
            for tid in existing_sigs.get(sig, []):
                ids_to_delete.add(tid)

        if ids_to_delete:
            to_delete = db.exec(
                select(Transaction).where(Transaction.user_id == uid, Transaction.id.in_(ids_to_delete))
            ).all()
            for t in to_delete:
                db.delete(t)
            db.commit()

    # Insert rows (auto-create missing categories/subcategories)
    for r in valid_rows:
        cat = _ensure_category(db, uid, r["category"])
        sub_id = None
        if r.get("subcategory"):
            sub = _ensure_subcategory(db, uid, cat.id, r["subcategory"])
            sub_id = sub.id

        t = Transaction(
            user_id=uid,
            date=r["date"],
            type=BudgetType(r["type"]),
            category_id=cat.id,
            subcategory_id=sub_id,
            description=r.get("description"),
            amount_cents=r["amount_cents"],
            currency=r["currency"].upper(),
            note=r.get("note"),
        )
        db.add(t)

    db.commit()

    request.session.pop("transaction_import_batch_id", None)
    _TX_IMPORT_BATCHES.pop(batch_id, None)

    return RedirectResponse(url="/transaction", status_code=303)
