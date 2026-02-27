"""Pulseway device model — synced from the RMM API."""

import logging
from datetime import datetime

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PulsewayDevice(models.Model):
    _name = "pulseway.device"
    _description = "Pulseway Device"
    _inherit = ["mail.thread"]
    _order = "name"
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    name = fields.Char(required=True, tracking=True)
    pulseway_id = fields.Char(
        string="Pulseway ID",
        required=True,
        index=True,
        copy=False,
        help="Unique device identifier from Pulseway.",
    )
    os_name = fields.Char(string="Operating System", readonly=True)
    os_version = fields.Char(string="OS Version", readonly=True)
    ip_address = fields.Char(string="IP Address", readonly=True)
    remote_address = fields.Char(string="Remote Address", readonly=True)
    group_name = fields.Char(string="Group", readonly=True)
    site_name = fields.Char(string="Site", readonly=True)
    organization_name = fields.Char(string="Organization", readonly=True)
    online = fields.Boolean(default=False, tracking=True, readonly=True)
    last_seen = fields.Datetime(readonly=True)
    last_sync = fields.Datetime(readonly=True, string="Last Synced")
    active = fields.Boolean(default=True)

    ticket_ids = fields.One2many(
        "helpdesk.ticket",
        "pulseway_device_id",
        string="Tickets",
    )
    ticket_count = fields.Integer(compute="_compute_ticket_count", string="Tickets")

    remote_control_url = fields.Char(
        compute="_compute_remote_control_url",
        string="Remote Control URL",
    )

    _sql_constraints = [
        (
            "pulseway_id_unique",
            "UNIQUE(pulseway_id)",
            "A device with this Pulseway ID already exists.",
        ),
    ]

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends("ticket_ids")
    def _compute_ticket_count(self):
        for rec in self:
            rec.ticket_count = len(rec.ticket_ids)

    @api.depends("pulseway_id")
    def _compute_remote_control_url(self):
        ICP = self.env["ir.config_parameter"].sudo()
        webapp_url = (ICP.get_param("pulseway_rmm.webapp_url") or "").rstrip("/")
        for rec in self:
            if webapp_url and rec.pulseway_id:
                rec.remote_control_url = f"{webapp_url}/#!/devices/{rec.pulseway_id}"
            else:
                rec.remote_control_url = False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_remote_control(self):
        """Open the Pulseway web dashboard for this device."""
        self.ensure_one()
        if not self.remote_control_url:
            return
        return {
            "type": "ir.actions.act_url",
            "url": self.remote_control_url,
            "target": "new",
        }

    def action_open_tickets(self):
        """Open tickets linked to this device."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tickets"),
            "res_model": "helpdesk.ticket",
            "view_mode": "list,form",
            "domain": [("pulseway_device_id", "=", self.id)],
        }

    def action_refresh_device(self):
        """Fetch fresh data for this single device from Pulseway."""
        self.ensure_one()
        api_client = self.env["pulseway.api"]
        raw = api_client.get_device(self.pulseway_id)
        self._update_from_api(raw)

    # ------------------------------------------------------------------
    # Sync logic
    # ------------------------------------------------------------------

    @api.model
    def cron_sync_devices(self):
        """Scheduled action: full sync of all devices from Pulseway."""
        api_client = self.env["pulseway.api"]
        try:
            raw_devices = api_client.get_devices()
        except Exception:
            _logger.exception("Pulseway device sync failed")
            return

        _logger.info("Pulseway sync: received %d devices", len(raw_devices))
        existing = {
            d.pulseway_id: d
            for d in self.search([("pulseway_id", "in", [r.get("Identifier") for r in raw_devices])])
        }

        for raw in raw_devices:
            identifier = raw.get("Identifier")
            if not identifier:
                continue
            device = existing.get(identifier)
            if device:
                device._update_from_api(raw)
            else:
                self._create_from_api(raw)

    def _update_from_api(self, raw):
        """Update an existing device record from API response dict."""
        vals = self._prepare_vals(raw)
        # Always write last_sync; compare other fields to skip no-op writes
        changed = {"last_sync": vals.pop("last_sync")}
        for key, new_val in vals.items():
            current = self[key]
            compare_new = new_val
            # Normalise datetimes to naive UTC for safe comparison
            if isinstance(current, datetime):
                current = current.replace(tzinfo=None)
            if isinstance(compare_new, datetime):
                compare_new = compare_new.replace(tzinfo=None)
            if current != compare_new:
                changed[key] = new_val
        self.write(changed)

    @api.model
    def _create_from_api(self, raw):
        """Create a new device record from API response dict."""
        vals = self._prepare_vals(raw)
        vals["pulseway_id"] = raw.get("Identifier")
        return self.create(vals)

    @api.model
    def _prepare_vals(self, raw):
        """Map Pulseway API fields to Odoo field values."""
        last_seen = raw.get("LastSeen")
        if last_seen and isinstance(last_seen, str):
            try:
                # Strip timezone to produce a naive-UTC datetime (Odoo convention)
                last_seen = datetime.fromisoformat(
                    last_seen.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, TypeError):
                last_seen = False

        return {
            "name": raw.get("Name") or raw.get("Identifier") or "Unknown",
            "os_name": raw.get("OsName") or raw.get("Os") or False,
            "os_version": raw.get("OsVersion") or False,
            "ip_address": raw.get("IpAddress") or False,
            "remote_address": raw.get("RemoteAddress") or False,
            "group_name": raw.get("GroupName") or raw.get("Group") or False,
            "site_name": raw.get("SiteName") or False,
            "organization_name": raw.get("OrganizationName") or False,
            "online": bool(raw.get("Online")),
            "last_seen": last_seen or False,
            "last_sync": fields.Datetime.now(),
        }
