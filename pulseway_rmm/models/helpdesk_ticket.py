"""Extend helpdesk tickets with Pulseway device linking."""

from odoo import fields, models


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    pulseway_device_id = fields.Many2one(
        "pulseway.device",
        string="Device",
        tracking=True,
        help="Pulseway RMM device linked to this ticket.",
    )
    device_online = fields.Boolean(
        related="pulseway_device_id.online",
        string="Device Online",
        store=True,
    )
    device_os = fields.Char(
        related="pulseway_device_id.os_name",
        string="Device OS",
    )
    device_ip = fields.Char(
        related="pulseway_device_id.ip_address",
        string="Device IP",
    )
    device_last_user = fields.Char(
        related="pulseway_device_id.last_logged_on_user",
        string="Device User",
        store=True,
    )

    def action_remote_control(self):
        """Open Pulseway remote control for the linked device."""
        self.ensure_one()
        if not self.pulseway_device_id:
            return
        return self.pulseway_device_id.action_open_remote_control()

    def action_refresh_device(self):
        """Refresh device data from Pulseway API."""
        self.ensure_one()
        if not self.pulseway_device_id:
            return
        self.pulseway_device_id.action_refresh_device()
