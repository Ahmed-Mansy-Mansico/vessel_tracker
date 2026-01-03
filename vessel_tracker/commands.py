import click

from vessel_tracker.vessel_tracker.workers.ais_stream import run as ais_run

@click.command('ais-worker')
def ais_worker():
    print("Starting AIS Worker...")
    ais_run()

    
commands = [ais_worker]