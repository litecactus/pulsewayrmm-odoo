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
        ICP.set_param("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_param("pulseway_rmm.token_id", "test-token-id")
        ICP.set_param("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_param("pulseway_rmm.webapp_url", "https://my.pulseway.com")
        cls.api = cls.env["pulseway.api"]

    def test_get_credentials_returns_config(self):
        base_url, token_id, token_secret, webapp_url = self.api._get_credentials()
        self.assertEqual(base_url, "https://api.pulseway.com/v3")
        self.assertEqual(token_id, "test-token-id")
        self.assertEqual(token_secret, "test-token-secret")
        self.assertEqual(webapp_url, "https://my.pulseway.com")

    def test_get_credentials_raises_when_missing(self):
        self.env["ir.config_parameter"].sudo().set_param(
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
        mock_request.assert_called_once()

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_request_connection_error(self, mock_request):
        import requests
        mock_request.side_effect = requests.ConnectionError("fail")
        with self.assertRaises(UserError):
            self.api._request("GET", "/devices")

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_request_timeout(self, mock_request):
        import requests
        mock_request.side_effect = requests.Timeout("timeout")
        with self.assertRaises(UserError):
            self.api._request("GET", "/devices")

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
    def test_request_invalid_json(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>not json</html>"
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_request.return_value = mock_resp
        with self.assertRaises(UserError):
            self.api._request("GET", "/devices")

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_test_connection(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"Data": []}'
        mock_resp.json.return_value = {"Data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        result = self.api.test_connection()
        self.assertTrue(result)
        mock_request.assert_called_once_with(
            "GET",
            "https://api.pulseway.com/v3/devices",
            auth=("test-token-id", "test-token-secret"),
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            timeout=30,
            params={"$top": 1},
        )

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_get_devices_paginates(self, mock_request):
        """Two pages of results then a short page terminates."""
        page1 = MagicMock()
        page1.status_code = 200
        page1.content = b"x"
        page1.json.return_value = {
            "Data": [{"Identifier": str(i)} for i in range(100)]
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.status_code = 200
        page2.content = b"x"
        page2.json.return_value = {"Data": [{"Identifier": "last"}]}
        page2.raise_for_status = MagicMock()

        mock_request.side_effect = [page1, page2]

        devices = self.api.get_devices()
        self.assertEqual(len(devices), 101)
        self.assertEqual(mock_request.call_count, 2)

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_get_device_returns_empty_on_missing_data(self, mock_request):
        """get_device returns {} when API response has no Data key."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"error": "not found"}'
        mock_resp.json.return_value = {"error": "not found"}
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        result = self.api.get_device("missing-id")
        self.assertEqual(result, {})
