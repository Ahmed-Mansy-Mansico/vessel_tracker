import frappe


def after_install():
    """Setup AIS stream background job after app installation"""
    from vessel_tracker.vessel_tracker.tasks import start_ais_stream_if_needed
    start_ais_stream_if_needed()
    frappe.db.commit()