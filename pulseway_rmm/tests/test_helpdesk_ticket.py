"""Tests for the helpdesk.ticket Pulseway extensions."""

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestHelpdeskTicketPulseway(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_param("pulseway_rmm.token_id", "test-token-id")
        ICP.set_param("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_param("pulseway_rmm.webapp_url", "https://my.pulseway.com")

        cls.device = cls.env["pulseway.device"].create(
            {
                "name": "Test Workstation",
                "pulseway_id": "ws-001",
                "online": True,
                "os_name": "Windows 11",
                "ip_address": "10.0.0.5",
            }
        )
        # Helpdesk team is required for ticket creation in v19
        cls.team = cls.env["helpdesk.team"].search([], limit=1)
        if not cls.team:
            cls.team = cls.env["helpdesk.team"].create({"name": "Test Team"})

    def _create_ticket(self, **overrides):
        vals = {
            "name": "Printer not working",
            "team_id": self.team.id,
            "pulseway_device_id": self.device.id,
        }
        vals.update(overrides)
        return self.env["helpdesk.ticket"].create(vals)

    def test_ticket_device_link(self):
        ticket = self._create_ticket()
        self.assertEqual(ticket.pulseway_device_id, self.device)
        self.assertTrue(ticket.device_online)
        self.assertEqual(ticket.device_os, "Windows 11")
        self.assertEqual(ticket.device_ip, "10.0.0.5")

    def test_ticket_without_device(self):
        ticket = self._create_ticket(pulseway_device_id=False)
        self.assertFalse(ticket.pulseway_device_id)
        self.assertFalse(ticket.device_online)

    def test_device_ticket_count(self):
        self._create_ticket()
        self._create_ticket(name="Another issue")
        self.device.invalidate_recordset()
        self.assertEqual(self.device.ticket_count, 2)

    def test_action_remote_control_from_ticket(self):
        ticket = self._create_ticket()
        result = ticket.action_remote_control()
        self.assertEqual(result["type"], "ir.actions.act_url")
        self.assertIn("ws-001", result["url"])

    def test_action_remote_control_no_device(self):
        ticket = self._create_ticket(pulseway_device_id=False)
        result = ticket.action_remote_control()
        self.assertIsNone(result)

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_action_refresh_device_from_ticket(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        mock_resp.json.return_value = {
            "Data": {
                "Identifier": "ws-001",
                "Name": "Updated Workstation",
                "Online": False,
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        ticket = self._create_ticket()
        ticket.action_refresh_device()
        self.assertEqual(self.device.name, "Updated Workstation")
        self.assertFalse(self.device.online)
