import frappe
from frappe.utils.background_jobs import enqueue


def start_ais_stream_if_needed():
    """Check if AIS stream job is running, if not start it"""
    
    # Check if there's already a running AIS stream job
    existing_jobs = frappe.get_all(
        "RQ Job", 
        filters={
            "job_name": "ais_stream_worker",
            "status": ["in", ["started", "queued"]]
        }
    )
    
    if not existing_jobs:
        # Start the AIS stream as a background job
        enqueue(
            'vessel_tracker.vessel_tracker.workers.ais_stream_background.run_ais_stream',
            queue='long',  # Use long queue for persistent connections
            timeout=None,  # No timeout
            job_name='ais_stream_worker',
            is_async=True
        )
        frappe.logger().info("Started AIS stream background job")
    else:
        frappe.logger().info("AIS stream job already running")