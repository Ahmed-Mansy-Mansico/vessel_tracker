### Vessel Tracker

Vessel Tracker

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app vessel_tracker
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/vessel_tracker
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit


## Need to run 
sudo nano /etc/systemd/system/ais-worker.service

Update Site config with the api key

[Unit]
Description=Frappe AIS Streaming Worker
After=network.target redis-server.service

[Service]
Type=simple
User=frappe
WorkingDirectory=/home/frappe/fmh-bench
ExecStart=/home/frappe/.local/bin/bench ais-worker
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target


sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable ais-worker
sudo systemctl start ais-worker


sudo systemctl status ais-worker


<!-- for logging -->
sudo systemctl restart ais-worker
sudo journalctl -u ais-worker -f

journalctl -u ais-worker -f
