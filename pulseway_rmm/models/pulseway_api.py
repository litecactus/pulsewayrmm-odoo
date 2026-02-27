"""Pulseway RMM API client as an Odoo abstract model.

Centralises all HTTP communication with the Pulseway REST API v3.
Other models call ``self.env["pulseway.api"].<method>()`` rather than
making requests directly.
"""

import logging
import time
from urllib.parse import quote

import requests
from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 30  # seconds
PAGE_SIZE = 100  # Pulseway v3 max $top
MAX_PAGES = 200  # safety cap: 20 000 devices
PAGE_DELAY = 1.1  # seconds between paginated requests (stay under 60 req/min)


class PulsewayApi(models.AbstractModel):
    _name = "pulseway.api"
    _description = "Pulseway API Client"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _get_credentials(self):
        """Return (base_url, token_id, token_secret, webapp_url) from config."""
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("pulseway_rmm.api_url") or "").rstrip("/")
        token_id = ICP.get_param("pulseway_rmm.token_id") or ""
        token_secret = ICP.get_param("pulseway_rmm.token_secret") or ""
        webapp_url = (ICP.get_param("pulseway_rmm.webapp_url") or "").rstrip("/")
        if not all([base_url, token_id, token_secret]):
            raise UserError(
                _(
                    "Pulseway RMM credentials are not configured. "
                    "Go to Settings > Pulseway RMM to set them up."
                )
            )
        return base_url, token_id, token_secret, webapp_url

    @api.model
    def _request(self, method, endpoint, **kwargs):
        """Execute an authenticated request against the Pulseway API.

        Returns the parsed JSON body on success; raises ``UserError`` on
        HTTP or connection errors.
        """
        base_url, token_id, token_secret, _webapp_url = self._get_credentials()
        url = f"{base_url}/{endpoint.lstrip('/')}"
        try:
            resp = requests.request(
                method,
                url,
                auth=(token_id, token_secret),
                timeout=TIMEOUT,
                **kwargs,
            )
            resp.raise_for_status()
        except requests.ConnectionError:
            raise UserError(
                _("Cannot connect to Pulseway at %s. Check the API URL.", base_url)
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "N/A"
            detail = ""
            if exc.response is not None:
                try:
                    detail = exc.response.text[:200]
                except Exception:
                    pass
            msg = _(
                "Pulseway API error (HTTP %s). "
                "Check credentials and API URL.",
                status,
            )
            if detail:
                msg += f"\n\nAPI response: {detail}"
            raise UserError(msg)
        except requests.Timeout:
            raise UserError(
                _("Pulseway API request timed out after %s seconds.", TIMEOUT)
            )
        except requests.RequestException:
            raise UserError(_("Pulseway API request failed unexpectedly."))
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            raise UserError(
                _("Pulseway API returned an invalid (non-JSON) response.")
            )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    @api.model
    def test_connection(self):
        """Verify that the stored credentials are valid.

        Returns ``True`` on success; raises ``UserError`` on failure.
        Uses the /systems endpoint (with $top=1 to minimise payload) because
        it is the most universally available v3 endpoint across Pulseway
        cloud and self-hosted deployments.
        """
        self._request("GET", "/systems", params={"$top": 1})
        return True

    @api.model
    def get_devices(self):
        """Fetch **all** devices, handling OData pagination automatically.

        Includes a delay between pages to respect the 60 req/min rate limit,
        and caps at ``MAX_PAGES`` to prevent infinite loops.
        """
        devices = []
        skip = 0
        for _page in range(MAX_PAGES):
            data = self._request(
                "GET",
                "/devices",
                params={"$top": PAGE_SIZE, "$skip": skip, "$count": "true"},
            )
            batch = data.get("Data") or []
            devices.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
            time.sleep(PAGE_DELAY)
        else:
            _logger.warning(
                "Pulseway sync hit page limit (%d pages / %d devices). "
                "Some devices may not have been synced.",
                MAX_PAGES,
                len(devices),
            )
        return devices

    @api.model
    def get_device(self, device_id):
        """Fetch a single device by its Pulseway identifier."""
        safe_id = quote(str(device_id), safe="")
        data = self._request("GET", f"/devices/{safe_id}")
        return data.get("Data") or {}

    @api.model
    def get_device_notifications(self, device_id):
        """Fetch recent notifications for a device."""
        safe_id = quote(str(device_id), safe="")
        data = self._request("GET", f"/devices/{safe_id}/notifications")
        return data.get("Data") or []
