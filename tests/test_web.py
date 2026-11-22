import io
import re
import tempfile
import unittest
from html import unescape
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
from homeio.adapters.auth import Authentication, password_hash, verify_password
from homeio.adapters.sqlite import connect, initialize
from homeio.config import Settings
from homeio.domain.accounting import Movement, ValidationError
from homeio.web.app import App


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.sqlite3"
        initialize(self.db)
        self.app = App(Settings(self.db, "a" * 48))
        self.app.auth.create_user("tester", "correct horse battery staple")
        self.cookie = ""
        self.csrf = ""

    def request(self, path="/", method="GET", form=None, host="localhost", **extra):
        path, _, query = path.partition("?")
        body = urlencode(form or {}).encode()
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "HTTP_HOST": host,
            "HTTP_COOKIE": self.cookie,
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(body),
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            **extra,
        }
        result = {}

        def start(status, headers):
            result["status"] = int(status.split()[0])
            result["headers"] = dict(headers)

        result["body"] = b"".join(self.app(environ, start)).decode()
        if "Set-Cookie" in result["headers"]:
            cookies = SimpleCookie(result["headers"]["Set-Cookie"])
            self.cookie = "homeio_session=" + cookies["homeio_session"].value
        match = re.search(r'name="csrf_token" value="([^"]+)"', result["body"])
        if match:
            self.csrf = match.group(1)
        return result

    def login(self):
        self.request("/login")
        return self.request(
            "/login",
            "POST",
            {
                "username": "tester",
                "password": "correct horse battery staple",
                "csrf_token": self.csrf,
            },
        )

    def test_auth_required_for_pages_api_and_writes(self):
        for path in ("/", "/movements", "/catalogs/category", "/api/summary"):
            response = self.request(path)
            self.assertEqual(response["status"], 303)
            self.assertEqual(response["headers"]["Location"], "/login")
        self.assertEqual(self.request("/movements/new", "POST")["status"], 303)

    def test_login_rotates_session_and_logout_revokes_it(self):
        self.request("/login")
        old_cookie = self.cookie
        response = self.login()
        self.assertEqual(response["status"], 303)
        self.assertNotEqual(self.cookie, old_cookie)
        cookie = self.cookie
        self.assertEqual(self.request("/")["status"], 200)
        self.assertEqual(self.request("/logout", "POST", {"csrf_token": self.csrf})["status"], 303)
        self.cookie = cookie
        self.assertEqual(self.request("/")["status"], 303)
        self.cookie = old_cookie
        self.assertEqual(self.request("/")["status"], 303)

    def test_csrf_login_and_authenticated_forms(self):
        self.request("/login")
        self.assertEqual(self.request("/login", "POST", {"username": "tester"})["status"], 403)
        self.login()
        self.assertEqual(
            self.request("/movements/new", "POST", {"description": "Attack"})["status"], 403
        )

    def test_safe_cookies_and_security_headers(self):
        response = self.request("/login")
        cookie = response["headers"]["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(response["headers"]["X-Frame-Options"], "DENY")
        self.assertIn("object-src 'none'", response["headers"]["Content-Security-Policy"])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_host_validation_and_static_traversal(self):
        self.assertEqual(self.request("/login", host="evil.example")["status"], 400)
        self.assertEqual(self.request("/static/../config.py")["status"], 404)
        self.assertEqual(self.request("/static/app.js")["status"], 200)

    def test_login_errors_do_not_disclose_user_existence(self):
        self.request("/login")
        for username in ("tester", "missing"):
            response = self.request(
                "/login",
                "POST",
                {"username": username, "password": "wrong password", "csrf_token": self.csrf},
            )
            self.assertEqual(response["status"], 401)
            self.assertIn("Usuario o contraseña incorrectos.", response["body"])

    def test_rate_limit_persists_across_application_instances(self):
        for _ in range(5):
            self.app.auth.login("tester", "wrong", "127.0.0.1")
        other = Authentication(self.db, "a" * 48)
        with self.assertRaises(ValidationError):
            other.login("tester", "correct horse battery staple", "127.0.0.1")

    def test_expired_session_rejected(self):
        self.login()
        with connect(self.db) as db:
            db.execute("UPDATE session SET expires_at=0")
        self.assertEqual(self.request("/")["status"], 303)

    def test_password_reset_revokes_sessions(self):
        self.login()
        self.app.auth.create_user("tester", "another strong password", reset=True)
        self.assertEqual(self.request("/")["status"], 303)

    def test_templates_crud_and_xss_escaping(self):
        self.login()
        self.request("/movements/new")
        response = self.request(
            "/movements/new",
            "POST",
            {
                "csrf_token": self.csrf,
                "description": "<script>alert(1)</script>",
                "valid_date": "2026-11-01",
                "amount": "12.34",
                "movement_type": "0",
            },
        )
        self.assertEqual(response["status"], 303)
        for path in (
            "/?month=2026-11",
            "/movements?month=2026-11",
            "/movements/1/edit",
            "/catalogs/category",
            "/catalogs/site",
        ):
            response = self.request(path)
            self.assertEqual(response["status"], 200, response["body"])
            self.assertNotIn("<script>alert(1)</script>", response["body"])
        self.assertIn("&lt;script&gt;", self.request("/?month=2026-11")["body"])
        response = self.request("/movements/1/archive", "POST", {"csrf_token": self.csrf})
        self.assertEqual(response["status"], 303)
        self.assertEqual(self.app.ledger.dashboard("2026-11")["expense"], 0)

    def test_validation_errors_and_missing_objects(self):
        self.login()
        self.request("/movements/new")
        response = self.request(
            "/movements/new",
            "POST",
            {
                "csrf_token": self.csrf,
                "description": "Invalid",
                "valid_date": "2026-02-30",
                "amount": "1",
                "movement_type": "0",
            },
        )
        self.assertEqual(response["status"], 400)
        self.assertEqual(self.request("/movements/999/edit")["status"], 404)
        self.assertEqual(self.request("/?month=2026-99")["status"], 400)
        self.assertEqual(self.request("/movements?page=-1")["status"], 400)

    def test_movement_filters_default_to_expenses_and_preserve_search(self):
        self.login()
        self.app.ledger.save_movement(Movement("Shared expense", "2026-11-01", 100, 0))
        for index in range(31):
            self.app.ledger.save_movement(Movement(f"Shared income {index}", "2026-11-01", 200, 1))
        self.app.ledger.save_movement(Movement("Other income", "2026-11-01", 300, 1))
        self.app.ledger.save_movement(Movement("Shared October", "2026-10-01", 300, 1))
        response = self.request("/movements?month=2026-11&q=Shared")
        self.assertEqual(response["status"], 200)
        self.assertIn("Shared expense", response["body"])
        self.assertNotIn("Shared income", response["body"])
        self.assertIn("1 resultados", response["body"])
        self.assertIn('aria-current="true">Gastos', response["body"])
        income_link = re.search(r'href="([^"]+)"[^>]*>Ingresos</a>', response["body"])
        response = self.request("/movements" + unescape(income_link.group(1)))
        self.assertEqual(response["status"], 200)
        self.assertIn("31 resultados", response["body"])
        self.assertNotIn("Shared expense", response["body"])
        self.assertNotIn("Other income", response["body"])
        self.assertNotIn("Shared October", response["body"])
        self.assertIn('name="movement_type" value="1"', response["body"])
        self.assertIn('aria-current="true">Ingresos', response["body"])
        next_link = re.search(r'href="([^"]+)">Siguiente</a>', response["body"])
        response = self.request("/movements" + unescape(next_link.group(1)))
        self.assertEqual(response["status"], 200)
        self.assertIn("Página 2", response["body"])
        self.assertEqual(response["body"].count('aria-label="Editar '), 1)
        expense_link = re.search(r'href="([^"]+)"[^>]*>Gastos</a>', response["body"])
        response = self.request("/movements" + unescape(expense_link.group(1)))
        self.assertIn("Página 1", response["body"])
        self.assertIn("Shared expense", response["body"])

    def test_invalid_movement_filters_are_rejected(self):
        self.login()
        for value in ("", "2", "-1", "expense", "0 OR 1=1"):
            with self.subTest(value=value):
                response = self.request("/movements?" + urlencode({"movement_type": value}))
                self.assertEqual(response["status"], 400)
        self.assertEqual(self.request("/logout")["status"], 405)

    def test_no_unexpected_exception_detail_leaks(self):
        self.login()
        with patch.object(self.app.ledger, "dashboard", side_effect=RuntimeError("SECRET")):
            with self.assertLogs("homeio.web.app", level="ERROR"):
                response = self.request("/")
        self.assertEqual(response["status"], 500)
        self.assertNotIn("SECRET", response["body"])

    def test_limits_and_duplicate_parameters(self):
        self.assertEqual(self.request("/login", "POST", CONTENT_LENGTH="70000")["status"], 413)
        self.assertEqual(self.request("/login?x=1&x=2")["status"], 400)

    def test_session_tokens_are_not_stored_in_plaintext(self):
        self.login()
        token = self.cookie.split("=", 1)[1]
        with connect(self.db) as db:
            hashes = [row[0] for row in db.execute("SELECT token_hash FROM session")]
        self.assertNotIn(token, hashes)

    def test_summary_json_has_exact_cents(self):
        self.login()
        self.app.ledger.save_movement(Movement("Test", "2026-11-01", 1234, 0))
        response = self.request("/api/summary?month=2026-11")
        self.assertEqual(response["status"], 200)
        self.assertIn('"expense": 1234', response["body"])

    def test_password_hashing(self):
        first, second = password_hash("a long password"), password_hash("a long password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("a long password", first))
        self.assertFalse(verify_password("wrong", first))
