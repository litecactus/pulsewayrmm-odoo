"""Tests for the pulseway.device model."""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


SAMPLE_DEVICE_RAW = {
    "Identifier": "aaaa-bbbb-cccc-dddd",
    "Name": "WORKSTATION-01",
    "OsName": "Windows 11 Pro",
    "OsVersion": "10.0.22631",
    "IpAddress": "192.168.1.100",
    "RemoteAddress": "203.0.113.5",
    "GroupName": "Servers",
    "SiteName": "Main Office",
    "OrganizationName": "Acme Corp",
    "Online": True,
    "LastSeen": "2025-12-01T10:30:00Z",
}


@tagged("post_install", "-at_install")
class TestPulsewayDevice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_param("pulseway_rmm.token_id", "test-token-id")
        ICP.set_param("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_param("pulseway_rmm.webapp_url", "https://my.pulseway.com")

    def _create_device(self, **overrides):
        vals = {
            "name": "Test Device",
            "pulseway_id": "test-id-001",
        }
        vals.update(overrides)
        return self.env["pulseway.device"].create(vals)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def test_create_device(self):
        device = self._create_device()
        self.assertEqual(device.name, "Test Device")
        self.assertEqual(device.pulseway_id, "test-id-001")

    def test_unique_pulseway_id(self):
        self._create_device(pulseway_id="unique-constraint-test")
        with self.assertRaises(Exception):
            self._create_device(pulseway_id="unique-constraint-test")

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    def test_remote_control_url(self):
        device = self._create_device()
        self.assertEqual(
            device.remote_control_url,
            "https://my.pulseway.com/#!/devices/test-id-001",
        )

    def test_remote_control_url_encodes_special_chars(self):
        device = self._create_device(pulseway_id="id with spaces/slashes")
        self.assertIn("id%20with%20spaces%2Fslashes", device.remote_control_url)

    def test_remote_control_url_without_webapp(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "pulseway_rmm.webapp_url", ""
        )
        device = self._create_device(pulseway_id="no-webapp-device")
        self.assertFalse(device.remote_control_url)

    def test_ticket_count(self):
        device = self._create_device()
        self.assertEqual(device.ticket_count, 0)

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def test_prepare_vals(self):
        vals = self.env["pulseway.device"]._prepare_vals(SAMPLE_DEVICE_RAW)
        self.assertEqual(vals["name"], "WORKSTATION-01")
        self.assertEqual(vals["os_name"], "Windows 11 Pro")
        self.assertTrue(vals["online"])
        self.assertIsNotNone(vals["last_sync"])

    def test_prepare_vals_missing_name_uses_identifier(self):
        raw = {"Identifier": "abc-123"}
        vals = self.env["pulseway.device"]._prepare_vals(raw)
        self.assertEqual(vals["name"], "abc-123")

    def test_prepare_vals_missing_everything(self):
        vals = self.env["pulseway.device"]._prepare_vals({})
        self.assertEqual(vals["name"], "Unknown")
        self.assertFalse(vals["online"])

    def test_create_from_api(self):
        device = self.env["pulseway.device"]._create_from_api(SAMPLE_DEVICE_RAW)
        self.assertEqual(device.pulseway_id, "aaaa-bbbb-cccc-dddd")
        self.assertEqual(device.name, "WORKSTATION-01")
        self.assertEqual(device.ip_address, "192.168.1.100")
        self.assertTrue(device.online)

    def test_create_from_api_missing_identifier(self):
        """Devices without Identifier are skipped."""
        result = self.env["pulseway.device"]._create_from_api({"Name": "No ID"})
        self.assertFalse(result)

    def test_update_from_api(self):
        device = self._create_device(pulseway_id="aaaa-bbbb-cccc-dddd")
        updated_raw = dict(SAMPLE_DEVICE_RAW, Name="WORKSTATION-01-NEW", Online=False)
        device._update_from_api(updated_raw)
        self.assertEqual(device.name, "WORKSTATION-01-NEW")
        self.assertFalse(device.online)

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_cron_sync_creates_and_updates(self, mock_request):
        """Full sync: creates new devices and updates existing ones."""
        self._create_device(pulseway_id="aaaa-bbbb-cccc-dddd", name="Old Name")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        mock_resp.json.return_value = {
            "Data": [
                SAMPLE_DEVICE_RAW,
                {"Identifier": "new-device-id", "Name": "NEW-SERVER", "Online": True},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        self.env["pulseway.device"].cron_sync_devices()

        existing = self.env["pulseway.device"].search(
            [("pulseway_id", "=", "aaaa-bbbb-cccc-dddd")]
        )
        self.assertEqual(existing.name, "WORKSTATION-01")

        new_dev = self.env["pulseway.device"].search(
            [("pulseway_id", "=", "new-device-id")]
        )
        self.assertTrue(new_dev)
        self.assertEqual(new_dev.name, "NEW-SERVER")

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_cron_sync_reactivates_archived_device(self, mock_request):
        """Archived device is reactivated when it reappears in the API."""
        device = self._create_device(
            pulseway_id="archived-dev", name="Archived", active=False
        )
        self.assertFalse(device.active)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        mock_resp.json.return_value = {
            "Data": [
                {"Identifier": "archived-dev", "Name": "Alive Again", "Online": True}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        self.env["pulseway.device"].cron_sync_devices()
        device.invalidate_recordset()
        self.assertTrue(device.active)
        self.assertEqual(device.name, "Alive Again")

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_cron_sync_deduplicates_identifiers(self, mock_request):
        """Duplicate Identifiers in API response are deduplicated."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        mock_resp.json.return_value = {
            "Data": [
                {"Identifier": "dup-001", "Name": "First", "Online": True},
                {"Identifier": "dup-001", "Name": "Second", "Online": False},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        self.env["pulseway.device"].cron_sync_devices()
        devices = self.env["pulseway.device"].search(
            [("pulseway_id", "=", "dup-001")]
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices.name, "Second")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def test_action_open_remote_control(self):
        device = self._create_device()
        result = device.action_open_remote_control()
        self.assertEqual(result["type"], "ir.actions.act_url")
        self.assertIn("test-id-001", result["url"])

    def test_action_open_tickets(self):
        device = self._create_device()
        result = device.action_open_tickets()
        self.assertEqual(result["res_model"], "helpdesk.ticket")
