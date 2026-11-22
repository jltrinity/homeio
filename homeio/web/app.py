"""Composition root and HTML delivery adapter."""

import hmac
import logging
import re
from datetime import date
from decimal import Decimal
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from jinja2 import Environment, FileSystemLoader, select_autoescape
from homeio.adapters.auth import Authentication
from homeio.adapters.sqlite import SQLiteLedger, connect
from homeio.application.accounting import Accounting
from homeio.config import Settings
from homeio.domain.accounting import Movement, ValidationError, money_to_cents
from homeio.web.framework import HTTPError, Request, Response, Router

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def euro(cents: int) -> str:
    formatted = f"{Decimal(cents) / 100:,.2f}"
    return formatted.translate(str.maketrans({",": ".", ".": ","})) + " €"


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.auth = Authentication(settings.database, settings.secret, settings.session_hours)
        self.ledger = SQLiteLedger(settings.database)
        self.accounting = Accounting(self.ledger)
        self.templates = Environment(
            loader=FileSystemLoader(ROOT / "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.templates.filters["euro"] = euro
        self.router = Router()
        for pattern, methods, handler in (
            (r"/health", ("GET",), self.health),
            (r"/static/(?P<name>[a-zA-Z0-9_.-]+)", ("GET",), self.static),
            (r"/login", ("GET", "POST"), self.login),
            (r"/logout", ("POST",), self.logout),
            (r"/", ("GET",), self.dashboard),
            (r"/api/summary", ("GET",), self.summary),
            (r"/movements", ("GET",), self.movements),
            (r"/movements/new", ("GET", "POST"), self.edit_movement),
            (r"/movements/(?P<item_id>\d+)/edit", ("GET", "POST"), self.edit_movement),
            (r"/movements/(?P<item_id>\d+)/archive", ("POST",), self.archive_movement),
            (r"/catalogs/(?P<table>category|site)", ("GET", "POST"), self.catalog),
        ):
            self.router.add(pattern, methods, handler)

    def __call__(self, environ, start_response):
        request = None
        try:
            request = Request(environ)
            try:
                host = urlsplit("//" + request.host)
                valid_host = (
                    host.hostname in self.settings.allowed_hosts
                    and not host.username
                    and not host.password
                    and not host.path
                    and not host.query
                    and not host.fragment
                )
                _ = host.port
            except ValueError:
                valid_host = False
            if not valid_host:
                raise HTTPError(400, "Host no permitido.")
            public = request.path in ("/login", "/health") or request.path.startswith("/static/")
            request.session = self.auth.session(request.token)
            if not public and (not request.session or not request.session["user_id"]):
                response = Response.redirect("/login")
            else:
                if request.method == "POST":
                    csrf = request.form.get("csrf_token", "")
                    if not request.session or not hmac.compare_digest(
                        csrf.encode(), request.session["csrf"].encode()
                    ):
                        raise HTTPError(403, "El formulario ha caducado. Recarga la página.")
                response = self.router.dispatch(request)
        except HTTPError as exc:
            response = self.render(
                "error.html", request, status=exc.status, message=exc.message, code=exc.status
            )
        except (ValidationError, ValueError):
            response = self.render(
                "error.html",
                request,
                status=400,
                message="Revisa los datos de la solicitud.",
                code=400,
            )
        except Exception:
            logger.exception("Unhandled request failure")
            response = self.render(
                "error.html",
                request,
                status=500,
                message="No se ha podido completar la operación.",
                code=500,
            )
        response.headers.extend(
            [
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "same-origin"),
                ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
                (
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
                    "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
                    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'",
                ),
            ]
        )
        if self.settings.https:
            response.headers.append(("Strict-Transport-Security", "max-age=31536000"))
        return response.send(start_response, head=environ.get("REQUEST_METHOD") == "HEAD")

    def render(
        self, template: str, request: Request | None, status: int = 200, **context
    ) -> Response:
        return Response(
            self.templates.get_template(template).render(
                session=request.session if request else None,
                path=request.path if request else "",
                today=date.today().isoformat(),
                **context,
            ),
            status,
        )

    def cookie(self, response: Response, token: str, lifetime: int) -> Response:
        cookie = SimpleCookie()
        cookie["homeio_session"] = token
        cookie["homeio_session"]["path"] = "/"
        cookie["homeio_session"]["httponly"] = True
        cookie["homeio_session"]["samesite"] = "Lax"
        cookie["homeio_session"]["max-age"] = lifetime
        if self.settings.cookie_secure:
            cookie["homeio_session"]["secure"] = True
        response.headers.append(("Set-Cookie", cookie.output(header="").strip()))
        return response

    def health(self, request: Request) -> Response:
        with connect(self.settings.database) as db:
            db.execute("SELECT version FROM schema_version").fetchone()
        return Response.json({"status": "ok"})

    def static(self, request: Request, name: str) -> Response:
        # Serve only known application assets, never arbitrary filesystem paths.
        types = {"app.css": "text/css", "app.js": "application/javascript"}
        if name not in types:
            raise HTTPError(404, "Archivo no encontrado.")
        return Response((ROOT / "static" / name).read_bytes(), content_type=types[name])

    def login(self, request: Request) -> Response:
        if request.session and request.session["user_id"]:
            return Response.redirect("/")
        error, status = "", 200
        if request.method == "POST":
            username = request.form.get("username", "")[:80]
            password = request.form.get("password", "")
            try:
                user_id = self.auth.login(username, password, request.ip)
                if user_id:
                    token, request.session = self.auth.start_session(user_id, request.token)
                    return self.cookie(Response.redirect("/"), token, self.auth.lifetime)
                error, status = "Usuario o contraseña incorrectos.", 401
            except ValidationError as exc:
                error, status = str(exc), 429
        if not request.session:
            token, request.session = self.auth.start_session()
            return self.cookie(self.render("login.html", request, error=error), token, 900)
        return self.render("login.html", request, status=status, error=error)

    def logout(self, request: Request) -> Response:
        self.auth.logout(request.token)
        return self.cookie(Response.redirect("/login"), "", 0)

    @staticmethod
    def month(request: Request) -> str:
        month = request.query.get("month", date.today().strftime("%Y-%m"))
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPError(400, "Selecciona un mes válido.")
        try:
            date.fromisoformat(month + "-01")
        except ValueError as exc:
            raise HTTPError(400, "Selecciona un mes válido.") from exc
        return month

    def dashboard(self, request: Request) -> Response:
        month = self.month(request)
        summary = self.ledger.dashboard(month)
        rows, count = self.ledger.movements(month)
        return self.render(
            "dashboard.html", request, month=month, summary=summary, movements=rows[:6], count=count
        )

    def summary(self, request: Request) -> Response:
        return Response.json(self.ledger.dashboard(self.month(request)))

    def movements(self, request: Request) -> Response:
        month = self.month(request)
        query = request.query.get("q", "")[:255]
        try:
            page = int(request.query.get("page", "1"))
            if not 1 <= page <= 1_000_000:
                raise ValueError
        except ValueError as exc:
            raise HTTPError(400, "Página inválida.") from exc
        rows, count = self.ledger.movements(month, query, page)
        params = {"month": month, "q": query}
        return self.render(
            "movements.html",
            request,
            movements=rows,
            count=count,
            month=month,
            query=query,
            page=page,
            previous="?" + urlencode(dict(params, page=page - 1)) if page > 1 else "",
            next="?" + urlencode(dict(params, page=page + 1)) if page * 30 < count else "",
        )

    def edit_movement(self, request: Request, item_id: str | None = None) -> Response:
        item = self.ledger.movement(int(item_id)) if item_id else None
        if item_id and not item:
            raise HTTPError(404, "El movimiento no existe.")
        values = (
            dict(item) if item else {"valid_date": date.today().isoformat(), "movement_type": 0}
        )
        if item:
            values["amount"] = str(Decimal(item["amount_cents"]) / 100)
        error = ""
        if request.method == "POST":
            values = request.form
            try:
                movement = Movement(
                    values.get("description", ""),
                    values.get("valid_date", ""),
                    money_to_cents(values.get("amount", "")),
                    int(values.get("movement_type", "-1")),
                    int(values["category_id"]) if values.get("category_id") else None,
                    int(values["site_id"]) if values.get("site_id") else None,
                )
                self.accounting.record(movement, int(item_id) if item_id else None)
                return Response.redirect(
                    "/movements?" + urlencode({"month": movement.valid_date[:7]})
                )
            except (ValidationError, ValueError) as exc:
                error = (
                    str(exc)
                    if isinstance(exc, ValidationError)
                    else "Revisa los campos seleccionados."
                )
        return self.render(
            "movement_form.html",
            request,
            status=400 if error else 200,
            values=values,
            error=error,
            item_id=item_id,
            categories=[
                row
                for row in self.ledger.catalogs("category")
                if row["active"] or (item and row["id"] == item["category_id"])
            ],
            sites=[
                row
                for row in self.ledger.catalogs("site")
                if row["active"] or (item and row["id"] == item["site_id"])
            ],
        )

    def archive_movement(self, request: Request, item_id: str) -> Response:
        item = self.ledger.movement(int(item_id))
        if not item:
            raise HTTPError(404, "El movimiento no existe.")
        self.accounting.archive(int(item_id))
        return Response.redirect("/movements?" + urlencode({"month": item["valid_date"][:7]}))

    def catalog(self, request: Request, table: str) -> Response:
        error = ""
        if request.method == "POST":
            try:
                self.ledger.save_catalog(
                    table,
                    request.form.get("name", ""),
                    int(request.form.get("movement_type", "-1")),
                    int(request.form["id"]) if request.form.get("id") else None,
                    int(request.form.get("active", "1")),
                )
                return Response.redirect("/catalogs/" + table)
            except (ValidationError, ValueError) as exc:
                error = str(exc) if isinstance(exc, ValidationError) else "Revisa los datos."
        return self.render(
            "catalog.html",
            request,
            status=400 if error else 200,
            table=table,
            items=self.ledger.catalogs(table),
            error=error,
        )


def create_app() -> App:
    return App(Settings.load())
