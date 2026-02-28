"""Tests for the pulseway.device model."""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


SAMPLE_DEVICE_RAW = {
    "Identifier": "aaaa-bbbb-cccc-dddd",
    "Name": "WORKSTATION-01",
    "GroupName": "Servers",
    "SiteName": "Main Office",
    "OrganizationName": "Acme Corp",
}

SAMPLE_ASSET_RAW = {
    "Identifier": "aaaa-bbbb-cccc-dddd",
    "Name": "WORKSTATION-01",
    "Description": "Windows 11 Pro (24H2)",
    "Type": "windows",
    "LastSeenOnline": "2026-02-27T22:00:00Z",
    "ExternalUrl": "https://itw.pulseway.com/app/main/systems/aaaa-bbbb-cccc-dddd/details",
    "PublicIpAddress": "203.0.113.5",
    "IpAddresses": [
        {"Name": "Ethernet", "MAC": "AA", "IPs": [{"IP": "192.168.1.100", "V6": False}]},
    ],
    "AssetInfo": [
        {
            "CategoryName": "Operating System",
            "CategoryData": {
                "Name": "Windows 11 Pro",
                "Version": "10.0.26100",
                "Last Logged On User": "ACME\\jsmith",
            },
        },
    ],
}


def _make_mock_response(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"x"
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@tagged("post_install", "-at_install")
class TestPulsewayDevice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_str("pulseway_rmm.token_id", "test-token-id")
        ICP.set_str("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_str("pulseway_rmm.webapp_url", "https://my.pulseway.com")

    def _create_device(self, **overrides):
        vals = {"name": "Test Device", "pulseway_id": "test-id-001"}
        vals.update(overrides)
        return self.env["pulseway.device"].create(vals)

    def test_prepare_vals(self):
        vals = self.env["pulseway.device"]._prepare_vals(SAMPLE_DEVICE_RAW)
        self.assertEqual(vals["name"], "WORKSTATION-01")
        self.assertEqual(vals["group_name"], "Servers")

    def test_prepare_asset_vals(self):
        vals = self.env["pulseway.device"]._prepare_asset_vals(SAMPLE_ASSET_RAW)
        self.assertEqual(vals["os_name"], "Windows 11 Pro")
        self.assertEqual(vals["ip_address"], "192.168.1.100")
        self.assertEqual(vals["last_logged_on_user"], "ACME\\jsmith")
        self.assertIn("itw.pulseway.com", vals["external_url"])
        self.assertIn("last_seen", vals)
        self.assertIn("online", vals)

    def test_update_from_asset(self):
        device = self._create_device()
        device._update_from_asset(SAMPLE_ASSET_RAW)
        self.assertEqual(device.os_name, "Windows 11 Pro")
        self.assertEqual(device.last_logged_on_user, "ACME\\jsmith")
        self.assertEqual(device.ip_address, "192.168.1.100")

    def test_remote_control_url(self):
        device = self._create_device(
            external_url="https://itw.pulseway.com/app/main/systems/test-id-001/details"
        )
        self.assertIn("remote-control", device.remote_control_url)

    @patch("odoo.addons.pulseway_rmm.models.pulseway_device._time.sleep")
    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_cron_sync_creates_and_updates(self, mock_request, _mock_sleep):
        self._create_device(pulseway_id="aaaa-bbbb-cccc-dddd", name="Old Name")

        def side_effect(method, url, **kwargs):
            if "/assets/" in url:
                return _make_mock_response({"Data": SAMPLE_ASSET_RAW})
            return _make_mock_response({
                "Data": [
                    SAMPLE_DEVICE_RAW,
                    {"Identifier": "new-device-id", "Name": "NEW-SERVER"},
                ]
            })

        mock_request.side_effect = side_effect
        self.env["pulseway.device"].cron_sync_devices()

        existing = self.env["pulseway.device"].search(
            [("pulseway_id", "=", "aaaa-bbbb-cccc-dddd")]
        )
        self.assertEqual(existing.name, "WORKSTATION-01")

        new_dev = self.env["pulseway.device"].search(
            [("pulseway_id", "=", "new-device-id")]
        )
        self.assertTrue(new_dev)
