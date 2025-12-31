from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sqlalchemy import or_

from ..db import get_session
from ..deps import current_user_id
from ..models import Budget, Category, Subcategory
from ..domain import BudgetType, RepeatUnit
from ..validators import validate_budget, ValidationError
from ..money import euros_to_cents, cents_to_euros_str, MoneyParseError

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# NOTE: early-stage in-memory store for import batches (good for dev/tests).
# In production, you'd move this to DB / Redis / filesystem.
_IMPORT_BATCHES: dict[str, dict] = {}


WEEKDAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

REPEAT_UNIT_MAP = {
    "week": "weekly",
    "weekly": "weekly",
    "month": "monthly",
    "monthly": "monthly",
    "year": "yearly",
    "yearly": "yearly",
}

SCHEDULE_MAP = {
    "": "one-time",
    "one-time": "one-time",
    "one_time": "one-time",
    "onetime": "one-time",
    "one time": "one-time",
    "recurring": "recurring",
    "repeat": "recurring",
}


def _parse_int(s: str | None) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_date_query(s: str | None) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _load_budget_page_data(
    db: Session,
    uid: int,
    filters: dict | None = None,
):
    filters = filters or {}

    categories = db.exec(
        select(Category).where(Category.user_id == uid).order_by(Category.name)
    ).all()

    subcategories = db.exec(
        select(Subcategory).where(Subcategory.user_id == uid).order_by(Subcategory.name)
    ).all()

    budgets_q = select(Budget).where(Budget.user_id == uid)

    # --- Filters (all optional) ---
    f_type = (filters.get("type") or "").strip().lower()
    if f_type in ("income", "expense"):
        budgets_q = budgets_q.where(Budget.type == BudgetType(f_type))

    f_schedule = (filters.get("schedule") or "").strip().lower()
    if f_schedule in ("one-time", "one_time", "onetime", "one time"):
        budgets_q = budgets_q.where(Budget.is_recurring == False)  # noqa: E712
    elif f_schedule in ("recurring", "repeat"):
        budgets_q = budgets_q.where(Budget.is_recurring == True)  # noqa: E712

    f_category_id = _parse_int(filters.get("category_id"))
    if f_category_id:
        budgets_q = budgets_q.where(Budget.category_id == f_category_id)

    f_subcategory_id = _parse_int(filters.get("subcategory_id"))
    if f_subcategory_id:
        budgets_q = budgets_q.where(Budget.subcategory_id == f_subcategory_id)

    q = (filters.get("q") or "").strip()
    if q:
        # note is nullable -> this still works fine (NULL won't match)
        budgets_q = budgets_q.where(Budget.note.contains(q))

    created_from = _parse_date_query(filters.get("created_from"))
    created_to = _parse_date_query(filters.get("created_to"))
    if created_from:
        dt_from = datetime.combine(created_from, time.min)
        budgets_q = budgets_q.where(Budget.created_at >= dt_from)
    if created_to:
        # inclusive end-date: < next day midnight
        dt_to = datetime.combine(created_to, time.min) + timedelta(days=1)
        budgets_q = budgets_q.where(Budget.created_at < dt_to)

    budgets = db.exec(budgets_q.order_by(Budget.created_at.desc())).all()

    categories_by_id = {c.id: c for c in categories}
    subcategories_by_id = {s.id: s for s in subcategories}

    return categories, subcategories, budgets, categories_by_id, subcategories_by_id


def _render_budget_page(
    request: Request,
    uid: int,
    db: Session,
    error: str | None = None,
    status_code: int = 200,
    filters: dict | None = None,
):
    categories, subcategories, budgets, categories_by_id, subcategories_by_id = _load_budget_page_data(
        db, uid, filters=filters
    )

    return templates.TemplateResponse(
        "budget.html",
        {
            "request": request,
            "title": "Budget",
            "user_id": uid,
            "categories": categories,
            "subcategories": subcategories,
            "budgets": budgets,
            "categories_by_id": categories_by_id,
            "subcategories_by_id": subcategories_by_id,
            "filters": filters or {},
            "error": error,
            "cents_to_euros_str": cents_to_euros_str,
        },
        status_code=status_code,
    )


def _sig_from_row(row: dict) -> tuple:
    """Signature used for duplicate detection (ignores note)."""
    return (
        row["type"],
        row["category"].strip().lower(),
        (row.get("subcategory") or "").strip().lower() or None,
        row["amount_cents"],
        row["currency"].upper(),
        row["is_recurring"],
        row.get("one_time_date"),
        row.get("repeat_unit"),
        row.get("repeat_interval"),
        row.get("weekday"),
        row.get("day_of_month"),
        row.get("start_date"),
        row.get("end_date"),
    )


def _sig_from_existing(
    b: Budget,
    cat_name: str,
    sub_name: str | None,
) -> tuple:
    return (
        b.type.value if hasattr(b.type, "value") else str(b.type),
        cat_name.strip().lower(),
        sub_name.strip().lower() if sub_name else None,
        b.amount_cents,
        b.currency.upper(),
        bool(b.is_recurring),
        b.one_time_date,
        b.repeat_unit.value if b.repeat_unit else None,
        b.repeat_interval,
        b.weekday,
        b.day_of_month,
        b.start_date,
        b.end_date,
    )


def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    return date.fromisoformat(s)


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

    # Normalize headers (strip)
    reader.fieldnames = [h.strip() for h in reader.fieldnames]

    required = {"type", "category", "amount", "currency"}
    missing = required - set(h.lower() for h in reader.fieldnames)
    if missing:
        return [], [{"rownum": 0, "error": f"Missing required columns: {', '.join(sorted(missing))}", "raw": {}}]

    valid: list[dict] = []
    invalid: list[dict] = []

    for i, raw in enumerate(reader, start=2):  # 1=header, data starts at 2
        # make a lower-keyed dict for robustness
        row = {}
        for k, v in raw.items():
            key = (k or "").strip().lower()
            if isinstance(v, list):
                val = " ".join(str(x) for x in v if x is not None).strip()
            else:
                val = (v or "").strip()
            row[key] = val

        try:
            btype = row.get("type", "").lower()
            if btype not in ("income", "expense"):
                raise ValueError("type must be 'income' or 'expense'.")

            category = row.get("category", "").strip()
            if not category:
                raise ValueError("category is required.")

            subcategory = row.get("subcategory", "").strip() or None

            amount_str = row.get("amount", "")
            amount_cents = euros_to_cents(amount_str)

            currency = (row.get("currency") or "EUR").strip().upper()
            if not currency:
                currency = "EUR"

            schedule_raw = (row.get("schedule") or "").strip().lower()
            schedule = SCHEDULE_MAP.get(schedule_raw, None)
            if schedule is None:
                raise ValueError("schedule must be 'one-time' or 'recurring' (or empty).")

            note = (row.get("note") or "").strip()
            # If the CSV row is one comma short, "note" often ends up in start_date/end_date.
            if not note:
                for k in ("end_date", "start_date"):
                    v = (row.get(k) or "").strip()
                    if not v:
                        continue
                    # If it's not an ISO date, treat it as note.
                    try:
                        date.fromisoformat(v)
                    except Exception:
                        note = v
                        row[k] = ""
                        break
            note = note or None

            if schedule == "one-time":
                one_time_date = _parse_date(row.get("date", ""))
                if one_time_date is None:
                    raise ValueError("date is required for one-time items (YYYY-MM-DD).")

                parsed = {
                    "type": btype,
                    "category": category,
                    "subcategory": subcategory,
                    "amount_cents": amount_cents,
                    "currency": currency,
                    "is_recurring": False,
                    "one_time_date": one_time_date,
                    "repeat_unit": None,
                    "repeat_interval": None,
                    "weekday": None,
                    "day_of_month": None,
                    "start_date": None,
                    "end_date": None,
                    "note": note,
                }
                valid.append(parsed)
                continue

            # recurring
            repeat_every = (row.get("repeat_every") or "").strip()
            if not repeat_every:
                raise ValueError("repeat_every is required for recurring items.")
            try:
                repeat_interval = int(repeat_every)
            except ValueError:
                raise ValueError("repeat_every must be a number (e.g., 1).")

            unit_raw = (row.get("repeat_unit") or "").strip().lower()
            unit_norm = REPEAT_UNIT_MAP.get(unit_raw, None)
            if not unit_norm:
                raise ValueError("repeat_unit must be 'week', 'month', or 'year' for recurring items.")

            repeat_unit = RepeatUnit(unit_norm)

            weekday = None
            day_of_month = None

            if repeat_unit == RepeatUnit.WEEKLY:
                wd_raw = (row.get("on_weekday") or "").strip().lower()
                if not wd_raw:
                    raise ValueError("on_weekday is required for weekly recurring items (e.g., Mon).")
                weekday = WEEKDAY_MAP.get(wd_raw, None)
                if weekday is None:
                    raise ValueError("on_weekday must be one of Mon/Tue/Wed/Thu/Fri/Sat/Sun.")
            else:
                dom_raw = (row.get("on_day") or "").strip()
                if not dom_raw:
                    raise ValueError("on_day is required for monthly/yearly recurring items (1..31).")
                try:
                    day_of_month = int(dom_raw)
                except ValueError:
                    raise ValueError("on_day must be a number (1..31).")

            start_date = _parse_date(row.get("start_date", ""))
            end_date = _parse_date(row.get("end_date", ""))

            parsed = {
                "type": btype,
                "category": category,
                "subcategory": subcategory,
                "amount_cents": amount_cents,
                "currency": currency,
                "is_recurring": True,
                "one_time_date": None,
                "repeat_unit": repeat_unit.value,
                "repeat_interval": repeat_interval,
                "weekday": weekday,
                "day_of_month": day_of_month,
                "start_date": start_date,
                "end_date": end_date,
                "note": note,
            }
            valid.append(parsed)

        except MoneyParseError as e:
            invalid.append({"rownum": i, "error": str(e), "raw": row})
        except Exception as e:
            invalid.append({"rownum": i, "error": str(e), "raw": row})

    return valid, invalid


def _ensure_category(db: Session, uid: int, name: str) -> Category:
    existing = db.exec(
        select(Category).where(Category.user_id == uid, Category.name == name)
    ).first()
    if existing:
        return existing
    c = Category(user_id=uid, name=name.strip(), icon=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _ensure_subcategory(db: Session, uid: int, category_id: int, name: str) -> Subcategory:
    existing = db.exec(
        select(Subcategory).where(
            Subcategory.user_id == uid,
            Subcategory.category_id == category_id,
            Subcategory.name == name,
        )
    ).first()
    if existing:
        return existing
    s = Subcategory(user_id=uid, category_id=category_id, name=name.strip(), icon=None)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/budgets")
def budgets_redirect():
    return RedirectResponse(url="/budget", status_code=303)


@router.get("/budget", response_class=HTMLResponse)
def list_budget(
    request: Request,
    type: str | None = None,  # query param
    schedule: str | None = None,
    category_id: str | None = None,
    subcategory_id: str | None = None,
    q: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    filters = {
        "type": (type or "").strip(),
        "schedule": (schedule or "").strip(),
        "category_id": (category_id or "").strip(),
        "subcategory_id": (subcategory_id or "").strip(),
        "q": (q or "").strip(),
        "created_from": (created_from or "").strip(),
        "created_to": (created_to or "").strip(),
    }
    return _render_budget_page(request, uid, db, filters=filters)


@router.get("/budget/subcategories", response_class=HTMLResponse)
def budget_subcategories(
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


@router.get("/budget/template.csv")
def download_budget_template(
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    header = [
        "type", "category", "subcategory", "amount", "currency",
        "schedule", "date",
        "repeat_every", "repeat_unit", "on_weekday", "on_day",
        "start_date", "end_date",
        "note",
    ]
    example_rows = [
        # recurring monthly
        ["expense", "Housing", "Rent", "900.00", "EUR", "recurring", "", "1", "month", "", "1", "2025-01-01", "", "Monthly rent"],
        # one-time
        ["expense", "Insurance", "", "120.50", "EUR", "one-time", "2025-02-01", "", "", "", "", "", "", "Car insurance"],
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
        headers={"Content-Disposition": 'attachment; filename="budget_template.csv"'},
    )


@router.get("/budget/import", response_class=HTMLResponse)
def import_budget_form(
    request: Request,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "budget_import.html",
        {"request": request, "title": "Import Budget CSV", "user_id": uid, "error": None},
    )


@router.post("/budget/import")
async def import_budget_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    if not file.filename.lower().endswith(".csv"):
        return templates.TemplateResponse(
            "budget_import.html",
            {"request": request, "title": "Import Budget CSV", "user_id": uid, "error": "Please upload a .csv file."},
            status_code=400,
        )

    data = await file.read()
    valid_rows, invalid_rows = _parse_csv(data)

    # compute existing budget signatures (by category/subcategory names)
    cats = db.exec(select(Category).where(Category.user_id == uid)).all()
    subs = db.exec(select(Subcategory).where(Subcategory.user_id == uid)).all()
    cat_by_id = {c.id: c.name for c in cats}
    sub_by_id = {s.id: (s.name, s.category_id) for s in subs}

    existing = db.exec(select(Budget).where(Budget.user_id == uid)).all()
    existing_sigs: dict[tuple, list[int]] = {}
    for b in existing:
        cat_name = cat_by_id.get(b.category_id, f"#{b.category_id}")
        sub_name = None
        if b.subcategory_id:
            sub_name = sub_by_id.get(b.subcategory_id, (None, None))[0]
        sig = _sig_from_existing(b, cat_name, sub_name)
        existing_sigs.setdefault(sig, []).append(b.id)

    duplicates = []
    for idx, r in enumerate(valid_rows):
        sig = _sig_from_row(r)
        if sig in existing_sigs:
            duplicates.append(idx)

    batch_id = str(uuid4())
    _IMPORT_BATCHES[batch_id] = {
        "uid": uid,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "duplicates_idx": duplicates,
        "existing_sigs": existing_sigs,  # used during apply for replace
    }

    request.session["budget_import_batch_id"] = batch_id
    return RedirectResponse(url="/budget/import/review", status_code=303)


@router.get("/budget/import/review", response_class=HTMLResponse)
def import_budget_review(
    request: Request,
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    batch_id = request.session.get("budget_import_batch_id")
    batch = _IMPORT_BATCHES.get(batch_id) if batch_id else None
    if not batch or batch.get("uid") != uid:
        return RedirectResponse(url="/budget/import", status_code=303)

    valid_rows = batch["valid_rows"]
    invalid_rows = batch["invalid_rows"]
    duplicates_idx = set(batch["duplicates_idx"])

    preview = []
    for i, r in enumerate(valid_rows[:25]):
        preview.append({"row": r, "is_duplicate": i in duplicates_idx})

    return templates.TemplateResponse(
        "budget_import_review.html",
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


@router.post("/budget/import/apply")
def import_budget_apply(
    request: Request,
    action: str = Form(...),  # "keep" or "replace"
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    batch_id = request.session.get("budget_import_batch_id")
    batch = _IMPORT_BATCHES.get(batch_id) if batch_id else None
    if not batch or batch.get("uid") != uid:
        return RedirectResponse(url="/budget/import", status_code=303)

    valid_rows: list[dict] = batch["valid_rows"]
    existing_sigs: dict[tuple, list[int]] = batch["existing_sigs"]

    if action not in ("keep", "replace"):
        return RedirectResponse(url="/budget/import/review", status_code=303)

    # If replace: delete existing duplicates (delete ALL matches, not just one)
    if action == "replace":
        ids_to_delete: set[int] = set()
        for r in valid_rows:
            sig = _sig_from_row(r)
            for bid in existing_sigs.get(sig, []):
                ids_to_delete.add(bid)

        if ids_to_delete:
            budgets_to_delete = db.exec(
                select(Budget).where(Budget.user_id == uid, Budget.id.in_(ids_to_delete))
            ).all()
            for b in budgets_to_delete:
                db.delete(b)
            db.commit()

    # Insert CSV rows (auto-create missing categories/subcategories)
    for r in valid_rows:
        cat = _ensure_category(db, uid, r["category"])
        sub_id = None
        if r.get("subcategory"):
            sub = _ensure_subcategory(db, uid, cat.id, r["subcategory"])
            sub_id = sub.id

        b = Budget(
            user_id=uid,
            type=BudgetType(r["type"]),
            category_id=cat.id,
            subcategory_id=sub_id,
            amount_cents=r["amount_cents"],
            currency=r["currency"].upper(),

            is_recurring=bool(r["is_recurring"]),
            one_time_date=r.get("one_time_date"),

            repeat_unit=RepeatUnit(r["repeat_unit"]) if r.get("repeat_unit") else None,
            repeat_interval=r.get("repeat_interval"),
            weekday=r.get("weekday"),
            day_of_month=r.get("day_of_month"),
            start_date=r.get("start_date"),
            end_date=r.get("end_date"),

            note=r.get("note"),
        )

        try:
            validate_budget(b)
        except ValidationError:
            continue

        db.add(b)

    db.commit()

    # cleanup
    request.session.pop("budget_import_batch_id", None)
    _IMPORT_BATCHES.pop(batch_id, None)

    return RedirectResponse(url="/budget", status_code=303)


@router.post("/budget")
def create_budget(
    request: Request,
    budget_type: BudgetType = Form(...),

    category_id: str = Form(""),
    subcategory_id: str = Form(""),

    amount_eur: str = Form(...),
    currency: str = Form("EUR"),

    one_time_date: date | None = Form(None),

    is_recurring: str = Form(""),
    repeat_unit: str = Form(""),
    repeat_interval: str = Form(""),
    day_of_month: str = Form(""),
    weekday: str = Form(""),
    start_date: date | None = Form(None),
    end_date: date | None = Form(None),

    note: str = Form(""),

    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    if not category_id.strip():
        return _render_budget_page(request, uid, db, error="Category is required.", status_code=400)

    try:
        category_id_int = int(category_id)
    except ValueError:
        return _render_budget_page(request, uid, db, error="Invalid category.", status_code=400)

    cat = db.exec(
        select(Category).where(Category.id == category_id_int, Category.user_id == uid)
    ).first()
    if not cat:
        return _render_budget_page(request, uid, db, error="Invalid category.", status_code=400)

    sub_id: int | None = None
    if subcategory_id.strip():
        try:
            sub_id = int(subcategory_id)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Invalid subcategory.", status_code=400)

        sub = db.exec(
            select(Subcategory).where(
                Subcategory.id == sub_id,
                Subcategory.user_id == uid,
                Subcategory.category_id == category_id_int,
            )
        ).first()
        if not sub:
            return _render_budget_page(
                request, uid, db, error="Invalid subcategory for selected category.", status_code=400
            )

    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    recurring = is_recurring.strip().lower() in ("on", "true", "1", "yes")

    ru: RepeatUnit | None = None
    if recurring and repeat_unit.strip():
        try:
            ru = RepeatUnit(repeat_unit.strip().lower())
        except ValueError:
            return _render_budget_page(request, uid, db, error="Invalid repeat_unit.", status_code=400)

    ri: int | None = None
    if recurring and repeat_interval.strip():
        try:
            ri = int(repeat_interval)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Interval must be a number.", status_code=400)

    dom: int | None = None
    if recurring and day_of_month.strip():
        try:
            dom = int(day_of_month)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Day of month must be a number.", status_code=400)

    wd: int | None = None
    if recurring and weekday.strip():
        try:

            wd = int(weekday)
        except ValueError:
            return _render_budget_page(request, uid, db, error="Weekday must be a number.", status_code=400)

    if not recurring and one_time_date is None:
        return _render_budget_page(
            request, uid, db, error="Date is required for one-time budget.", status_code=400
        )

    b = Budget(
        user_id=uid,
        type=budget_type,
        category_id=category_id_int,
        subcategory_id=sub_id,
        amount_cents=amount_cents,
        currency=currency.strip().upper(),

        is_recurring=recurring,
        one_time_date=None if recurring else one_time_date,

        repeat_unit=ru if recurring else None,
        repeat_interval=ri if recurring else None,
        day_of_month=dom if recurring else None,
        weekday=wd if recurring else None,
        start_date=start_date if recurring else None,
        end_date=end_date if recurring else None,

        note=(note.strip() or None),
    )

    try:
        validate_budget(b)
    except ValidationError as e:
        return _render_budget_page(request, uid, db, error=str(e), status_code=400)

    db.add(b)
    db.commit()

    return RedirectResponse(url="/budget", status_code=303)


@router.get("/budget/{budget_id}/edit", response_class=HTMLResponse)
def edit_budget_form(
    request: Request,
    budget_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    budget = db.exec(select(Budget).where(Budget.id == budget_id, Budget.user_id == uid)).first()
    if not budget:
        return RedirectResponse(url="/budget", status_code=303)

    categories = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
    subcategories = db.exec(
        select(Subcategory)
        .where(Subcategory.user_id == uid, Subcategory.category_id == budget.category_id)
        .order_by(Subcategory.name)
    ).all()

    return templates.TemplateResponse(
        "budget_edit.html",
        {
            "request": request,
            "title": "Edit Budget",
            "user_id": uid,
            "budget": budget,
            "categories": categories,
            "subcategories": subcategories,
            "error": None,
            "cents_to_euros_str": cents_to_euros_str,
        },
    )


@router.post("/budget/{budget_id}/edit")
def edit_budget_apply(
    request: Request,
    budget_id: int,
    budget_type: BudgetType = Form(...),

    category_id: str = Form(""),
    subcategory_id: str = Form(""),

    amount_eur: str = Form(...),
    currency: str = Form("EUR"),

    one_time_date: date | None = Form(None),

    is_recurring: str = Form(""),
    repeat_unit: str = Form(""),
    repeat_interval: str = Form(""),
    day_of_month: str = Form(""),
    weekday: str = Form(""),
    start_date: date | None = Form(None),
    end_date: date | None = Form(None),

    note: str = Form(""),

    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    budget = db.exec(select(Budget).where(Budget.id == budget_id, Budget.user_id == uid)).first()
    if not budget:
        return RedirectResponse(url="/budget", status_code=303)

    if not category_id.strip():
        return edit_budget_form(request, budget_id, db, uid)

    try:
        category_id_int = int(category_id)
    except ValueError:
        return edit_budget_form(request, budget_id, db, uid)

    cat = db.exec(select(Category).where(Category.id == category_id_int, Category.user_id == uid)).first()
    if not cat:
        return edit_budget_form(request, budget_id, db, uid)

    sub_id: int | None = None
    if subcategory_id.strip():
        try:
            sub_id = int(subcategory_id)
        except ValueError:
            sub_id = None

        if sub_id is not None:
            sub = db.exec(
                select(Subcategory).where(
                    Subcategory.id == sub_id,
                    Subcategory.user_id == uid,
                    Subcategory.category_id == category_id_int,
                )
            ).first()
            if not sub:
                sub_id = None

    try:
        amount_cents = euros_to_cents(amount_eur)
    except MoneyParseError:
        # reuse edit form with same page
        categories = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        subcategories = db.exec(
            select(Subcategory)
            .where(Subcategory.user_id == uid, Subcategory.category_id == category_id_int)
            .order_by(Subcategory.name)
        ).all()
        return templates.TemplateResponse(
            "budget_edit.html",
            {
                "request": request,
                "title": "Edit Budget",
                "user_id": uid,
                "budget": budget,
                "categories": categories,
                "subcategories": subcategories,
                "error": "Invalid amount.",
                "cents_to_euros_str": cents_to_euros_str,
            },
            status_code=400,
        )

    recurring = is_recurring.strip().lower() in ("on", "true", "1", "yes")

    ru: RepeatUnit | None = None
    if recurring and repeat_unit.strip():
        try:
            ru = RepeatUnit(repeat_unit.strip().lower())
        except ValueError:
            ru = None

    ri: int | None = None
    if recurring and repeat_interval.strip():
        try:
            ri = int(repeat_interval)
        except ValueError:
            ri = None

    dom: int | None = None
    if recurring and day_of_month.strip():
        try:
            dom = int(day_of_month)
        except ValueError:
            dom = None

    wd: int | None = None
    if recurring and weekday.strip():
        try:
            wd = int(weekday)
        except ValueError:
            wd = None

    if not recurring and one_time_date is None:
        categories = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        subcategories = db.exec(
            select(Subcategory)
            .where(Subcategory.user_id == uid, Subcategory.category_id == category_id_int)
            .order_by(Subcategory.name)
        ).all()
        return templates.TemplateResponse(
            "budget_edit.html",
            {
                "request": request,
                "title": "Edit Budget",
                "user_id": uid,
                "budget": budget,
                "categories": categories,
                "subcategories": subcategories,
                "error": "Date is required for one-time budget.",
                "cents_to_euros_str": cents_to_euros_str,
            },
            status_code=400,
        )

    # apply updates
    budget.type = budget_type
    budget.category_id = category_id_int
    budget.subcategory_id = sub_id
    budget.amount_cents = amount_cents
    budget.currency = currency.strip().upper()

    budget.is_recurring = recurring
    budget.one_time_date = None if recurring else one_time_date

    budget.repeat_unit = ru if recurring else None
    budget.repeat_interval = ri if recurring else None
    budget.day_of_month = dom if recurring else None
    budget.weekday = wd if recurring else None
    budget.start_date = start_date if recurring else None
    budget.end_date = end_date if recurring else None

    budget.note = (note.strip() or None)

    try:
        validate_budget(budget)
    except ValidationError as e:
        categories = db.exec(select(Category).where(Category.user_id == uid).order_by(Category.name)).all()
        subcategories = db.exec(
            select(Subcategory)
            .where(Subcategory.user_id == uid, Subcategory.category_id == category_id_int)
            .order_by(Subcategory.name)
        ).all()
        return templates.TemplateResponse(
            "budget_edit.html",
            {
                "request": request,
                "title": "Edit Budget",
                "user_id": uid,
                "budget": budget,
                "categories": categories,
                "subcategories": subcategories,
                "error": str(e),
                "cents_to_euros_str": cents_to_euros_str,
            },
            status_code=400,
        )

    db.add(budget)
    db.commit()

    return RedirectResponse(url="/budget", status_code=303)


@router.post("/budget/{budget_id}/delete")
def delete_budget(
    request: Request,
    budget_id: int,
    db: Session = Depends(get_session),
    uid: int | None = Depends(current_user_id),
):
    if not uid:
        return RedirectResponse(url="/login", status_code=303)

    budget = db.exec(select(Budget).where(Budget.id == budget_id, Budget.user_id == uid)).first()
    if budget:
        db.delete(budget)
        db.commit()

    return RedirectResponse(url="/budget", status_code=303)
