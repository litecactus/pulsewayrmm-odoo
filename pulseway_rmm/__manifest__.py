{
    "name": "Pulseway RMM Integration",
    "version": "19.0.1.0.0",
    "category": "Services/Helpdesk",
    "summary": "Link Pulseway RMM devices to helpdesk tickets with remote control",
    "description": """
        Integrates Pulseway RMM with Odoo Helpdesk:
        - Sync devices from Pulseway RMM
        - Link devices to helpdesk tickets
        - Launch remote control sessions from tickets
        - View device status and details
    """,
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["helpdesk"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/cron_data.xml",
        "views/pulseway_device_views.xml",
        "views/helpdesk_ticket_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": True,
}
