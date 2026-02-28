"""Tests for the Pulseway API client (pulseway.api abstract model)."""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPulsewayApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_str("pulseway_rmm.token_id", "test-token-id")
        ICP.set_str("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_str("pulseway_rmm.webapp_url", "https://my.pulseway.com")
        cls.api = cls.env["pulseway.api"]

    def test_get_credentials_raises_when_missing(self):
        self.env["ir.config_parameter"].sudo().set_str(
            "pulseway_rmm.token_id", ""
        )
        with self.assertRaises(UserError):
            self.api._get_credentials()

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_request_success(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"Data": []}'
        mock_resp.json.return_value = {"Data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        result = self.api._request("GET", "/devices")
        self.assertEqual(result, {"Data": []})

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_request_http_error(self, mock_request):
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=mock_resp)
        mock_request.return_value = mock_resp
        with self.assertRaises(UserError):
            self.api._request("GET", "/devices")

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_get_asset(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        mock_resp.json.return_value = {
            "Data": {"Identifier": "dev-123", "LastSeenOnline": "2026-02-27T22:00:00Z"}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        result = self.api.get_asset("dev-123")
        self.assertEqual(result["Identifier"], "dev-123")
