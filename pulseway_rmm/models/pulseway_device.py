"""Pulseway device model — synced from the RMM API."""

import logging
import time as _time
from datetime import datetime, timezone
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

PAGE_DELAY = 1.1  # seconds between API calls (stay under 60 req/min)


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
    last_logged_on_user = fields.Char(
        string="Last Logged On User",
        readonly=True,
        index=True,
        help="Last user who logged on to this device (from Pulseway asset info).",
    )
    external_url = fields.Char(
        string="Pulseway URL",
        readonly=True,
        help="Direct link to this device in the Pulseway web app.",
    )
    device_type = fields.Char(string="Device Type", readonly=True)

    ticket_ids = fields.One2many(
        "helpdesk.ticket",
        "pulseway_device_id",
        string="Tickets",
    )
    ticket_count = fields.Integer(compute="_compute_ticket_count", string="Ticket Count")

    remote_control_url = fields.Char(
        compute="_compute_remote_control_url",
        string="Remote Control URL",
    )

    _pulseway_id_unique = models.Constraint(
        "UNIQUE(pulseway_id)",
        "A device with this Pulseway ID already exists.",
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends("ticket_ids")
    def _compute_ticket_count(self):
        if not self.ids:
            self.ticket_count = 0
            return
        ticket_data = self.env["helpdesk.ticket"]._read_group(
            domain=[("pulseway_device_id", "in", self.ids)],
            groupby=["pulseway_device_id"],
            aggregates=["__count"],
        )
        counts = {device.id: count for device, count in ticket_data}
        for rec in self:
            rec.ticket_count = counts.get(rec.id, 0)

    @api.depends("pulseway_id", "external_url")
    def _compute_remote_control_url(self):
        ICP = self.env["ir.config_parameter"].sudo()
        webapp_url = (ICP.get_str("pulseway_rmm.webapp_url") or "").rstrip("/")
        for rec in self:
            if rec.external_url:
                # ExternalUrl from API ends with /details — replace with /remote-control
                base = rec.external_url
                if base.endswith("/details"):
                    base = base[:-len("/details")]
                rec.remote_control_url = f"{base}/details/remote-control"
            elif webapp_url and rec.pulseway_id:
                safe_id = quote(str(rec.pulseway_id), safe="")
                rec.remote_control_url = (
                    f"{webapp_url}/app/main/systems/{safe_id}"
                    f"/details/remote-control"
                )
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
        """Fetch fresh data for this single device from Pulseway.

        Uses sudo() for the write so read-only Pulseway users can trigger
        a refresh. The API call itself is safe (read-only GET).
        """
        self.ensure_one()
        self._check_pulseway_group()
        api_client = self.env["pulseway.api"]
        raw = api_client.get_device(self.pulseway_id)
        if not raw:
            return
        self.sudo()._update_from_api(raw)
        # Fetch rich asset data (online status, last user, IPs, etc.)
        asset = api_client.get_asset(self.pulseway_id)
        if asset:
            self.sudo()._update_from_asset(asset)

    def _check_pulseway_group(self):
        """Raise AccessError if the user has no Pulseway group."""
        if not self.env.su and not self.env.user.has_group(
            "pulseway_rmm.group_pulseway_user"
        ):
            raise AccessError(
                _("You need the Pulseway User role to perform this action.")
            )

    # ------------------------------------------------------------------
    # Sync logic
    # ------------------------------------------------------------------

    @api.model
    def cron_sync_devices(self):
        """Scheduled action: full sync of all devices from Pulseway."""
        api_client = self.env["pulseway.api"]
        try:
            raw_devices = api_client.get_devices()
        except (UserError, ConnectionError, OSError):
            _logger.exception("Pulseway device sync failed: could not fetch devices")
            return

        _logger.info("Pulseway sync: received %d devices", len(raw_devices))

        # Deduplicate by Identifier (last occurrence wins)
        seen_ids = {}
        for raw in raw_devices:
            identifier = raw.get("Identifier")
            if identifier:
                seen_ids[identifier] = raw
        raw_devices = list(seen_ids.values())

        # Include archived devices so we don't try to recreate them
        existing = {
            d.pulseway_id: d
            for d in self.with_context(active_test=False).search(
                [("pulseway_id", "in", list(seen_ids.keys()))]
            )
        }

        synced = 0
        failed = 0
        for raw in raw_devices:
            identifier = raw.get("Identifier")
            try:
                with self.env.cr.savepoint():
                    device = existing.get(identifier)
                    if device:
                        if not device.active:
                            device.active = True
                        device._update_from_api(raw)
                    else:
                        self._create_from_api(raw)
                    synced += 1
            except Exception:
                failed += 1
                _logger.exception("Pulseway sync: failed to sync device %s", identifier)

        if failed:
            _logger.warning(
                "Pulseway sync (phase 1 — list): %d synced, %d failed",
                synced,
                failed,
            )
        else:
            _logger.info(
                "Pulseway sync (phase 1 — list): %d devices synced", synced
            )

        # Phase 2: fetch rich asset data per device (online status, user, IPs)
        all_devices = self.with_context(active_test=False).search([])
        asset_ok = 0
        asset_fail = 0
        for device in all_devices:
            try:
                asset = api_client.get_asset(device.pulseway_id)
                if asset:
                    device._update_from_asset(asset)
                    asset_ok += 1
            except Exception:
                asset_fail += 1
                _logger.debug(
                    "Pulseway sync: asset fetch failed for %s",
                    device.pulseway_id,
                    exc_info=True,
                )
            _time.sleep(PAGE_DELAY)

        _logger.info(
            "Pulseway sync (phase 2 — assets): %d updated, %d failed",
            asset_ok,
            asset_fail,
        )

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
        identifier = raw.get("Identifier")
        if not identifier:
            _logger.warning("Pulseway sync: skipping device with no Identifier")
            return self.browse()
        vals = self._prepare_vals(raw)
        vals["pulseway_id"] = identifier
        return self.create(vals)

    @api.model
    def _prepare_vals(self, raw):
        """Map Pulseway /devices list API fields to Odoo field values."""
        return {
            "name": raw.get("Name") or raw.get("Identifier") or "Unknown",
            "group_name": raw.get("GroupName") or raw.get("Group") or False,
            "site_name": raw.get("SiteName") or False,
            "organization_name": raw.get("OrganizationName") or False,
            "last_sync": fields.Datetime.now(),
        }

    @api.model
    def _prepare_asset_vals(self, asset_data):
        """Map Pulseway /assets/{id} response to Odoo field values."""
        vals = {}

        # Online status + last_seen from LastSeenOnline
        last_seen_str = asset_data.get("LastSeenOnline")
        if last_seen_str and isinstance(last_seen_str, str):
            try:
                dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                last_seen = dt.astimezone(timezone.utc).replace(tzinfo=None)
                vals["last_seen"] = last_seen
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                vals["online"] = (now_utc - last_seen).total_seconds() < 900
            except (ValueError, TypeError):
                pass

        # External URL for remote control
        external_url = asset_data.get("ExternalUrl")
        if external_url:
            vals["external_url"] = external_url

        # Device type (windows, mac, linux)
        device_type = asset_data.get("Type")
        if device_type:
            vals["device_type"] = device_type

        # OS info and Last Logged On User from AssetInfo categories
        for cat in asset_data.get("AssetInfo") or []:
            cat_name = cat.get("CategoryName", "")
            cat_data = cat.get("CategoryData") or {}
            if cat_name == "Operating System":
                os_name = cat_data.get("Name")
                if os_name:
                    vals["os_name"] = os_name
                os_version = cat_data.get("Version")
                if os_version:
                    vals["os_version"] = os_version
                last_user = cat_data.get("Last Logged On User")
                if last_user:
                    vals["last_logged_on_user"] = last_user

        # Fallback OS name from Description
        if "os_name" not in vals:
            desc = asset_data.get("Description")
            if desc:
                vals["os_name"] = desc

        # IP address: first non-APIPA IPv4 from IpAddresses array
        for iface in asset_data.get("IpAddresses") or []:
            for ip_info in iface.get("IPs") or []:
                ip = ip_info.get("IP", "")
                if ip and not ip.startswith("169.254.") and not ip_info.get("V6"):
                    vals["ip_address"] = ip
                    break
            if "ip_address" in vals:
                break

        # Public IP
        public_ip = asset_data.get("PublicIpAddress")
        if public_ip:
            vals["remote_address"] = public_ip

        return vals

    def _update_from_asset(self, asset_data):
        """Update device record from /assets/{id} response."""
        vals = self._prepare_asset_vals(asset_data)
        if not vals:
            return
        changed = {}
        for key, new_val in vals.items():
            current = self[key]
            compare_new = new_val
            if isinstance(current, datetime):
                current = current.replace(tzinfo=None)
            if isinstance(compare_new, datetime):
                compare_new = compare_new.replace(tzinfo=None)
            if current != compare_new:
                changed[key] = new_val
        if changed:
            self.write(changed)
