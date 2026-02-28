"""Tests for the helpdesk.ticket Pulseway extensions."""

from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHelpdeskTicketPulseway(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("pulseway_rmm.api_url", "https://api.pulseway.com/v3")
        ICP.set_str("pulseway_rmm.token_id", "test-token-id")
        ICP.set_str("pulseway_rmm.token_secret", "test-token-secret")
        ICP.set_str("pulseway_rmm.webapp_url", "https://my.pulseway.com")

        cls.env.user.group_ids += cls.env.ref("pulseway_rmm.group_pulseway_user")

        cls.device = cls.env["pulseway.device"].create(
            {
                "name": "Test Workstation",
                "pulseway_id": "ws-001",
                "online": True,
                "os_name": "Windows 11",
                "ip_address": "10.0.0.5",
                "last_logged_on_user": "CORP\\testuser",
            }
        )
        cls.team = cls.env["helpdesk.team"].with_context(
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
        ).create({
            "name": "Pulseway Test Team",
            "member_ids": cls.env.user.ids,
            "auto_assignment": False,
            "use_sla": False,
        })
        cls.env["helpdesk.stage"].create({
            "name": "New",
            "sequence": 10,
            "team_ids": [(4, cls.team.id)],
        })

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
        self.assertEqual(ticket.device_last_user, "CORP\\testuser")

    def test_action_remote_control(self):
        ticket = self._create_ticket()
        result = ticket.action_remote_control()
        self.assertEqual(result["type"], "ir.actions.act_url")
        self.assertIn("ws-001", result["url"])

    @patch("odoo.addons.pulseway_rmm.models.pulseway_api.requests.request")
    def test_action_refresh_device(self, mock_request):
        def side_effect(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"x"
            resp.raise_for_status = MagicMock()
            if "/assets/" in url:
                resp.json.return_value = {
                    "Data": {
                        "LastSeenOnline": "2020-01-01T00:00:00Z",
                        "AssetInfo": [
                            {
                                "CategoryName": "Operating System",
                                "CategoryData": {
                                    "Name": "Windows 10",
                                    "Last Logged On User": "ACME\\jdoe",
                                },
                            }
                        ],
                    }
                }
            else:
                resp.json.return_value = {
                    "Data": {"Identifier": "ws-001", "Name": "Updated Workstation"}
                }
            return resp

        mock_request.side_effect = side_effect

        ticket = self._create_ticket()
        ticket.action_refresh_device()
        self.device.invalidate_recordset()
        self.assertEqual(self.device.name, "Updated Workstation")
        self.assertEqual(self.device.last_logged_on_user, "ACME\\jdoe")
