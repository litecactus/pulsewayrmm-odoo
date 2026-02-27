"""Settings for Pulseway RMM integration."""

from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pulseway_api_url = fields.Char(
        string="API URL",
        config_parameter="pulseway_rmm.api_url",
        default="https://api.pulseway.com/v3",
        help="Pulseway REST API v3 base URL.",
    )
    pulseway_token_id = fields.Char(
        string="Token ID",
        config_parameter="pulseway_rmm.token_id",
        help="API Token ID from Pulseway Administration > API Access.",
    )
    pulseway_token_secret = fields.Char(
        string="Token Secret",
        config_parameter="pulseway_rmm.token_secret",
        help="API Token Secret from Pulseway Administration > API Access.",
    )
    pulseway_webapp_url = fields.Char(
        string="Web App URL",
        config_parameter="pulseway_rmm.webapp_url",
        default="https://my.pulseway.com",
        help="Pulseway web dashboard URL, used for remote control links.",
    )

    def action_pulseway_test_connection(self):
        """Test the Pulseway API connection with current settings."""
        # Persist current form values so _get_credentials reads them
        self.set_values()
        self.env["pulseway.api"].test_connection()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Successfully connected to Pulseway RMM."),
                "type": "success",
                "sticky": False,
            },
        }
