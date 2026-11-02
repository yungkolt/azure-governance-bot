"""Azure Functions entry point (Python v2 programming model).

The v2 model uses decorators instead of a function.json per function.
Two triggers:
  - Timer: runs the scan automatically (default: weekdays 14:00 UTC = 6am PT)
  - HTTP:  run on demand, returns the JSON report (handy for demos)

Handlers are deliberately thin: all logic lives in governance/runner.py.
"""

import json
import logging

import azure.functions as func

from governance.azure_clients import build_clients
from governance.config import load_settings
from governance.runner import run_scan

app = func.FunctionApp()


# NCRONTAB has 6 fields (with seconds): sec min hour day month day-of-week
@app.timer_trigger(schedule="%GOV_SCHEDULE%", arg_name="timer", run_on_startup=False)
def scheduled_scan(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("Timer is past due; running anyway")
    settings = load_settings()
    report = run_scan(build_clients(settings.subscription_ids), settings, notify=True)
    logging.info("Scan %s complete: %d findings, ~$%s/mo waste",
                 report.run_id, len(report.findings), report.total_est_monthly_waste)


# FUNCTION auth level = caller needs a function key. Never ANONYMOUS for this.
@app.route(route="scan", methods=["GET", "POST"], auth_level=func.AuthLevel.FUNCTION)
def scan_now(req: func.HttpRequest) -> func.HttpResponse:
    settings = load_settings()
    notify = req.params.get("notify", "false").lower() == "true"
    report = run_scan(build_clients(settings.subscription_ids), settings, notify=notify)
    return func.HttpResponse(
        json.dumps(report.to_dict(), indent=2), mimetype="application/json", status_code=200
    )
