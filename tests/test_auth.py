"""Auth failure mapping. No live TIDAL session."""

from __future__ import annotations

import unittest

from requests import HTTPError, Response
from tidalapi.exceptions import AuthenticationError, ObjectNotFound, StreamNotAvailable

from felix.tidal.auth import AuthError, expired_message, is_auth_failure, raise_if_auth


class TestAuthFailure(unittest.TestCase):
    def test_expired_message_points_at_login(self) -> None:
        self.assertIn("login.py", expired_message())

    def test_authentication_error(self) -> None:
        exc = AuthenticationError(
            "Authentication failed with error 'invalid_grant: Token is expired or revoked'"
        )
        self.assertTrue(is_auth_failure(exc))
        with self.assertRaises(AuthError) as caught:
            raise_if_auth(exc)
        self.assertEqual(str(caught.exception), expired_message())

    def test_existing_auth_error_is_not_rewritten(self) -> None:
        original = AuthError("尚未登入，請先執行 scripts/login.py")
        with self.assertRaises(AuthError) as caught:
            raise_if_auth(original)
        self.assertIs(caught.exception, original)

    def test_http_401(self) -> None:
        resp = Response()
        resp.status_code = 401
        self.assertTrue(is_auth_failure(HTTPError(response=resp)))

    def test_catalog_miss_is_not_auth(self) -> None:
        self.assertFalse(is_auth_failure(ObjectNotFound("Object not found")))
        self.assertFalse(is_auth_failure(StreamNotAvailable("no stream")))
        self.assertFalse(is_auth_failure(ValueError("找不到曲目 304661213")))
