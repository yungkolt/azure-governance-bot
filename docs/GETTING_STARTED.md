# Getting started

Run these stages in order. Each one adds a single new moving part, so a failure points to one cause.

| Stage | Needs Azure | Cost | Changes anything in Azure |
|---|---|---|---|
| 1. Unit tests | No | Free | No |
| 2. Read-only scan | Yes | Free | No |
| 3. Test environment | Yes | Cents | Creates one resource group |
| 4. Local Functions host | Yes | Free | No |
| 5. Teams report | Yes | Free | No |
| 6. Deploy | Yes | Low | Creates a Function App |

## Prerequisites
- Python 3.11 or later
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- An Azure subscription you own. A personal pay-as-you-go or free-trial subscription is recommended.
- For stage 4: [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) and [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite)

## 1. Unit tests (offline)
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -v
ruff check .
```
Expected: all tests pass. These use an in-memory fake, so no Azure access is involved.

## 2. Read-only scan against your subscription
```bash
az login
az account show --query "{name:name, id:id}" -o table   # confirm the right subscription
export GOV_SUBSCRIPTION_IDS=$(az account show --query id -o tsv)
python -m governance.cli -v --json report.json
```
This only reads inventory. It's safe to run against any subscription where you hold Reader, though the results depend on what already exists there.

Before running the same query in code, try it in the portal: **Resource Graph Explorer**, then paste the `KQL` string from `governance/scanners/orphaned_disks.py`.

## 3. Disposable test environment
```bash
./scripts/create-lab.sh           # creates rg-gov-lab with known issues
# wait about a minute for Resource Graph to index the new resources
python -m governance.cli -v
```
Expected: one orphaned disk and at least two untagged findings in `rg-gov-lab`.

Clean up when you're done:
```bash
az group delete -n rg-gov-lab --yes --no-wait
```

## 4. Local Azure Functions host
```bash
cp local.settings.example.json local.settings.json
azurite --silent &                # local storage emulator required by the timer trigger
func start
```
Call the HTTP trigger from another terminal:
```bash
curl "http://localhost:7071/api/scan"
```
The JSON response is the same report the CLI produces.

## 5. Teams report
1. In Teams, open **Workflows** and create a flow from a template that posts to a channel when a webhook request is received.
2. Copy the generated URL into `TEAMS_WEBHOOK_URL`. Treat it as a secret.
3. Run `python -m governance.cli --teams`.

## 6. Deploy
See `scripts/deploy.sh`. Run it a section at a time and check each resource in the portal before moving to the next.

## Cost safeguard
Before stage 3, create a budget alert on your subscription (**Cost Management**, then **Budgets**), for example $10 per month with email alerts at 50% and 100%.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| `DefaultAzureCredential failed to retrieve a token` | Not logged in. Run `az login`. |
| Scan returns no rows | Wrong subscription selected, or resources created less than a minute ago |
| `AuthorizationFailed` | The identity lacks Reader on the subscription |
| `func start` fails on the timer trigger | Azurite isn't running |
