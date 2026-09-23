"""Application web FastAPI - "Ordre de travail" (port multi-utilisateur de l'app desktop)."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, db, extraction, ocr_engine, payslip_parser, paypal, stats, storage
from app.config import DATA_DIR, PAYPAL_CLIENT_ID, PAYPAL_PLAN_ID, PAYPAL_WEBHOOK_ID
from app.models import SUMMARY_FIELD_NAMES, Payslip, WorkOrder, split_trajet

app = FastAPI(title="Ordre de travail")

# Chemins accessibles sans abonnement actif : la page d'abonnement elle-même, l'auth, et les
# assets statiques. Tout le reste est bloqué (redirigé vers /billing) pour un compte connecté
# sans accès actif (voir db.has_active_access).
GATE_ALLOWLIST_PREFIXES = ("/billing", "/login", "/register", "/logout", "/static", "/health")


@app.middleware("http")
async def subscription_gate(request: Request, call_next):
    path = request.url.path
    if not path.startswith(GATE_ALLOWLIST_PREFIXES):
        user = auth.get_current_user(request)
        if user and not db.has_active_access(user):
            return RedirectResponse("/billing", status_code=303)
    return await call_next(request)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

TMP_DIR = DATA_DIR / "tmp"


def fr_date(value: str) -> str:
    """Affiche une date ISO (YYYY-MM-DD, format de stockage) en JJ/MM/AAAA."""
    if not value:
        return value
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


templates.env.filters["fr_date"] = fr_date


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def _redirect(url: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status_code)


def _current_user(request: Request) -> dict | None:
    return auth.get_current_user(request)


# --- Authentification ---------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _current_user(request):
        return _redirect("/history")
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = db.get_user_by_email(email)
    if not user or not auth.verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Email ou mot de passe incorrect."}
        )
    resp = _redirect("/history")
    token = auth.make_session_token(user["id"])
    resp.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if _current_user(request):
        return _redirect("/history")
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@app.post("/register")
def register_submit(
    request: Request, email: str = Form(...), password: str = Form(...), password2: str = Form(...)
):
    email = email.strip().lower()
    if not email or "@" not in email:
        return templates.TemplateResponse(
            "register.html", {"request": request, "error": "Email invalide."}
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Le mot de passe doit faire au moins 8 caractères."},
        )
    if password != password2:
        return templates.TemplateResponse(
            "register.html", {"request": request, "error": "Les mots de passe ne correspondent pas."}
        )
    if db.get_user_by_email(email):
        return templates.TemplateResponse(
            "register.html", {"request": request, "error": "Un compte existe déjà avec cet email."}
        )
    user_id = db.create_user(email, auth.hash_password(password))
    resp = _redirect("/history")
    token = auth.make_session_token(user_id)
    resp.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = _redirect("/login")
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.get("/")
def index(request: Request):
    return _redirect("/history" if _current_user(request) else "/login")


# --- Import ---------------------------------------------------------------

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    pending = db.list_pending_import_jobs(user["id"])
    return templates.TemplateResponse(
        "import.html", {"request": request, "user": user, "pending": pending}
    )


def _run_extraction_job(token: str, paths: list[Path]) -> None:
    """Exécuté en arrière-plan (threadpool) par BackgroundTasks : l'utilisateur peut quitter
    la page pendant ce temps, voir GET /import/status/{token}."""
    try:
        pages = []
        for p in paths:
            pages.extend(ocr_engine.load_pages(p))
        result = extraction.extract_from_pages(pages)
        db.set_import_job_result(token, {
            "driver_name": result.driver_name,
            "matricule": result.matricule,
            "date": result.date,
            "summary": result.summary,
            "trajets": result.trajets,
            "last_minute_change": result.last_minute_change,
            "warnings": result.warnings,
        })
    except Exception as exc:  # noqa: BLE001
        db.set_import_job_error(token, str(exc))


@app.post("/import", response_class=HTMLResponse)
async def import_upload(request: Request, files: list[UploadFile], background_tasks: BackgroundTasks):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    if not files or not files[0].filename:
        return templates.TemplateResponse(
            "import.html",
            {"request": request, "user": user, "pending": db.list_pending_import_jobs(user["id"]),
             "error": "Choisis au moins un fichier."},
        )

    token = uuid.uuid4().hex
    tmp_dir = TMP_DIR / token
    tmp_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    for f in files:
        dest = tmp_dir / f.filename
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved_paths.append(dest)

    db.create_import_job(token, user["id"])
    background_tasks.add_task(_run_extraction_job, token, saved_paths)

    return _redirect(f"/import/status/{token}")


@app.get("/import/status/{token}", response_class=HTMLResponse)
def import_status(request: Request, token: str):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    job = db.get_import_job(user["id"], token)
    if job is None:
        return _redirect("/import")

    if job["status"] == "pending":
        return templates.TemplateResponse(
            "import_processing.html", {"request": request, "user": user, "token": token}
        )

    if job["status"] == "error":
        return templates.TemplateResponse(
            "import_error.html",
            {"request": request, "user": user, "token": token, "error": job["error_message"]},
        )

    result = json.loads(job["result_json"])
    known_lignes = db.list_known_lignes(user["id"])
    return templates.TemplateResponse(
        "import_review.html",
        {
            "request": request,
            "user": user,
            "token": token,
            "result": result,
            "summary_fields": SUMMARY_FIELD_NAMES,
            "trajets_text": "\n".join(result["trajets"]),
            "known_lignes": known_lignes,
        },
    )


@app.post("/import/status/{token}/discard")
def import_discard(request: Request, token: str):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    db.delete_import_job(user["id"], token)
    shutil.rmtree(TMP_DIR / token, ignore_errors=True)
    return _redirect("/import")


@app.get("/import/status/{token}/check")
def import_status_check(request: Request, token: str):
    """Petit endpoint JSON interrogé par la page d'attente (évite de recharger toute la page
    tant que l'extraction n'est pas terminée)."""
    user = _current_user(request)
    if not user:
        return {"status": "error"}
    job = db.get_import_job(user["id"], token)
    return {"status": job["status"] if job else "error"}


@app.post("/import/save")
async def import_save(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    form = await request.form()
    token = form.get("token", "")
    tmp_dir = TMP_DIR / token
    if not tmp_dir.exists():
        return _redirect("/import")

    wo = WorkOrder()
    wo.date = form.get("date", "").strip()
    wo.driver_name = form.get("driver_name", "").strip().upper()
    wo.matricule = form.get("matricule", "").strip()
    wo.notes = form.get("notes", "").strip()
    wo.last_minute_change = form.get("last_minute_change") == "on"
    for name in SUMMARY_FIELD_NAMES:
        try:
            setattr(wo, name, float((form.get(name, "0") or "0").replace(",", ".")))
        except ValueError:
            setattr(wo, name, 0.0)
    trajets_text = form.get("trajets", "")
    wo.trajets = [line.strip() for line in trajets_text.splitlines() if line.strip()]

    source_paths = sorted(tmp_dir.iterdir())
    filename, source_type = storage.store_source_files(user["id"], source_paths, wo.date)
    wo.source_filename = filename
    wo.source_type = source_type

    db.insert_work_order(user["id"], wo)
    db.delete_import_job(user["id"], token)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return _redirect("/history")


# --- Historique -------------------------------------------------------------

@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    order = "asc" if request.query_params.get("sort") == "asc" else "desc"
    work_orders = db.list_work_orders(user["id"], order=order)
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "user": user, "work_orders": work_orders, "sort": order},
    )


@app.get("/history/{work_order_id}/edit", response_class=HTMLResponse)
def edit_work_order_page(request: Request, work_order_id: int):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    wo = db.get_work_order(user["id"], work_order_id)
    if wo is None:
        return _redirect("/history")
    return templates.TemplateResponse(
        "edit_work_order.html",
        {
            "request": request,
            "user": user,
            "wo": wo,
            "summary_fields": SUMMARY_FIELD_NAMES,
            "trajets_text": "\n".join(wo.trajets),
        },
    )


@app.post("/history/{work_order_id}/edit")
async def edit_work_order_submit(request: Request, work_order_id: int):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    wo = db.get_work_order(user["id"], work_order_id)
    if wo is None:
        return _redirect("/history")
    form = await request.form()
    wo.date = form.get("date", "").strip()
    wo.driver_name = form.get("driver_name", "").strip().upper()
    wo.matricule = form.get("matricule", "").strip()
    wo.notes = form.get("notes", "").strip()
    wo.last_minute_change = form.get("last_minute_change") == "on"
    for name in SUMMARY_FIELD_NAMES:
        try:
            setattr(wo, name, float((form.get(name, "0") or "0").replace(",", ".")))
        except ValueError:
            setattr(wo, name, 0.0)
    trajets_text = form.get("trajets", "")
    wo.trajets = [line.strip() for line in trajets_text.splitlines() if line.strip()]
    db.update_work_order(user["id"], wo)
    return _redirect("/history")


@app.post("/history/{work_order_id}/delete")
def delete_work_order(request: Request, work_order_id: int):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    wo = db.get_work_order(user["id"], work_order_id)
    if wo is not None and wo.source_filename:
        storage.delete_source_file(user["id"], wo.source_filename)
    db.delete_work_order(user["id"], work_order_id)
    return _redirect("/history")


# --- Statistiques -----------------------------------------------------------

@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    uid = user["id"]
    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "user": user,
            "weekly": stats.weekly_totals(uid),
            "monthly": stats.monthly_totals(uid),
            "yearly": stats.yearly_totals(uid),
            "summary": stats.summary_for_period(uid),
            "top_trajets": stats.top_trajets(uid),
            "hours_to_hm": stats.hours_to_hm,
        },
    )


# --- Feuilles de paie ---------------------------------------------------

@app.get("/payslips", response_class=HTMLResponse)
def payslips_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        "payslips.html", {"request": request, "user": user, "payslips": db.list_payslips(user["id"])}
    )


@app.get("/payslips/new", response_class=HTMLResponse)
def payslip_new_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse("payslip_new.html", {"request": request, "user": user, "error": None})


@app.post("/payslips/new", response_class=HTMLResponse)
async def payslip_upload(request: Request, file: UploadFile):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    if not file.filename:
        return templates.TemplateResponse(
            "payslip_new.html", {"request": request, "user": user, "error": "Choisis un fichier PDF."}
        )
    token = uuid.uuid4().hex
    tmp_dir = TMP_DIR / token
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / file.filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    data = payslip_parser.extract_payslip(dest)

    return templates.TemplateResponse(
        "payslip_review.html",
        {"request": request, "user": user, "token": token, "data": data},
    )


@app.post("/payslips/save")
async def payslip_save(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    form = await request.form()
    token = form.get("token", "")
    tmp_dir = TMP_DIR / token
    if not tmp_dir.exists():
        return _redirect("/payslips")

    p = Payslip()
    p.period_start = form.get("period_start", "").strip()
    p.period_end = form.get("period_end", "").strip()
    for field_name in ("hs_25", "hs_50", "cumul_hs_25", "cumul_hs_50", "repos_differe"):
        try:
            setattr(p, field_name, float((form.get(field_name, "0") or "0").replace(",", ".")))
        except ValueError:
            setattr(p, field_name, 0.0)
    recap_json = form.get("recap_json", "{}")
    compteurs_json = form.get("compteurs_json", "{}")
    try:
        details = {"recap": json.loads(recap_json), "compteurs": json.loads(compteurs_json)}
    except json.JSONDecodeError:
        details = {"recap": {}, "compteurs": {}}
    p.details_json = json.dumps(details, ensure_ascii=False)

    source_path = next(tmp_dir.iterdir())
    p.source_filename = storage.store_payslip_file(user["id"], source_path, p.period_start)

    db.insert_payslip(user["id"], p)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return _redirect("/payslips")


@app.get("/payslips/{payslip_id}", response_class=HTMLResponse)
def payslip_detail(request: Request, payslip_id: int):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    p = db.get_payslip(user["id"], payslip_id)
    if p is None:
        return _redirect("/payslips")
    details = {"recap": {}, "compteurs": {}}
    if p.details_json:
        try:
            details = json.loads(p.details_json)
        except json.JSONDecodeError:
            pass
    return templates.TemplateResponse(
        "payslip_detail.html", {"request": request, "user": user, "p": p, "details": details}
    )


@app.post("/payslips/{payslip_id}/delete")
def payslip_delete(request: Request, payslip_id: int):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    p = db.get_payslip(user["id"], payslip_id)
    if p is not None and p.source_filename:
        storage.delete_payslip_file(user["id"], p.source_filename)
    db.delete_payslip(user["id"], payslip_id)
    return _redirect("/payslips")


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Abonnement PayPal ---------------------------------------------------

@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    return templates.TemplateResponse(
        "billing.html",
        {
            "request": request,
            "user": user,
            "has_access": db.has_active_access(user),
            "paypal_client_id": PAYPAL_CLIENT_ID,
            "paypal_plan_id": PAYPAL_PLAN_ID,
        },
    )


@app.post("/billing/confirm")
async def billing_confirm(request: Request):
    user = _current_user(request)
    if not user:
        return {"ok": False}
    body = await request.json()
    subscription_id = body.get("subscription_id", "")
    if not subscription_id:
        return {"ok": False}

    try:
        sub = paypal.get_subscription(subscription_id)
    except paypal.PayPalError:
        return {"ok": False}

    if sub.get("plan_id") != PAYPAL_PLAN_ID:
        return {"ok": False}

    status = "active" if sub.get("status") == "ACTIVE" else "none"
    db.set_subscription(user["id"], subscription_id, status)
    return {"ok": status == "active"}


@app.post("/billing/cancel")
def billing_cancel(request: Request):
    user = _current_user(request)
    if not user:
        return _redirect("/login")
    sub_id = user.get("paypal_subscription_id")
    if sub_id:
        try:
            paypal.cancel_subscription(sub_id)
        except paypal.PayPalError:
            pass
        db.set_subscription(user["id"], sub_id, "cancelled")
    return _redirect("/billing")


@app.post("/billing/webhook")
async def billing_webhook(request: Request):
    raw_body = await request.body()
    body_text = raw_body.decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}

    try:
        verified = paypal.verify_webhook_signature(headers, body_text, PAYPAL_WEBHOOK_ID)
    except paypal.PayPalError:
        verified = False
    if not verified:
        return {"ok": False}

    event = json.loads(body_text)
    event_type = event.get("event_type", "")
    resource = event.get("resource", {})
    subscription_id = resource.get("id") or resource.get("billing_agreement_id")
    if not subscription_id:
        return {"ok": True}

    if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
        db.set_subscription_status_by_id(subscription_id, "active")
    elif event_type in (
        "BILLING.SUBSCRIPTION.CANCELLED",
        "BILLING.SUBSCRIPTION.EXPIRED",
        "BILLING.SUBSCRIPTION.SUSPENDED",
    ):
        db.set_subscription_status_by_id(subscription_id, "cancelled")

    return {"ok": True}
