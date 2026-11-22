"""A small WSGI HTTP boundary: routing, parsing, and responses."""

import json
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def fields(raw: str) -> dict[str, str]:
    try:
        values = parse_qs(
            raw, keep_blank_values=True, max_num_fields=30, encoding="utf-8", errors="strict"
        )
        if any(len(value) != 1 for value in values.values()):
            raise ValueError
        return {key: value[0] for key, value in values.items()}
    except (ValueError, UnicodeError) as exc:
        raise HTTPError(400, "Parámetros inválidos.") from exc


class Request:
    def __init__(self, environ: dict):
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/")
        self.query = fields(environ.get("QUERY_STRING", ""))
        self.ip = environ.get("REMOTE_ADDR", "")
        self.host = environ.get("HTTP_HOST", "").lower()
        try:
            self.cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
        except CookieError as exc:
            raise HTTPError(400, "Cookie inválida.") from exc
        self.form = {}
        self.session = None
        if self.method == "POST":
            if environ.get("CONTENT_TYPE", "").split(";")[0] != "application/x-www-form-urlencoded":
                raise HTTPError(415, "Formato de formulario no compatible.")
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError as exc:
                raise HTTPError(400, "Longitud inválida.") from exc
            if not 0 <= length <= 65536:
                raise HTTPError(413, "El formulario es demasiado grande.")
            try:
                body = environ["wsgi.input"].read(length).decode("utf-8")
            except UnicodeError as exc:
                raise HTTPError(400, "Codificación inválida.") from exc
            self.form = fields(body)

    @property
    def token(self) -> str:
        cookie = self.cookies.get("homeio_session")
        return cookie.value if cookie else ""


@dataclass
class Response:
    body: bytes | str = b""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    headers: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def redirect(cls, path: str) -> "Response":
        if not path.startswith("/") or path.startswith("//") or "\n" in path or "\r" in path:
            raise ValueError("Redirect must be a local path")
        return cls(status=303, headers=[("Location", path)])

    @classmethod
    def json(cls, value: object) -> "Response":
        return cls(json.dumps(value), content_type="application/json; charset=utf-8")

    def send(self, start_response, *, head: bool = False):
        body = self.body.encode("utf-8") if isinstance(self.body, str) else self.body
        headers = [("Content-Type", self.content_type), ("Content-Length", str(len(body)))]
        start_response(f"{self.status} {HTTPStatus(self.status).phrase}", headers + self.headers)
        return [b"" if head else body]


class Router:
    def __init__(self):
        self.routes = []

    def add(self, pattern: str, methods: tuple[str, ...], handler) -> None:
        self.routes.append((re.compile(pattern), methods, handler))

    def dispatch(self, request: Request) -> Response:
        matched = False
        for pattern, methods, handler in self.routes:
            match = pattern.fullmatch(request.path)
            if match:
                matched = True
                method = "GET" if request.method == "HEAD" else request.method
                if method in methods:
                    return handler(request, **match.groupdict())
        if matched:
            raise HTTPError(405, "Método no permitido.")
        raise HTTPError(404, "La página no existe.")
