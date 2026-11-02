# Getting started

Run these stages in order. Each one adds a single new moving part, so a failure points to one cause.

| Stage | Needs Azure | Cost | Changes anything in Azure |
|---|---|---|---|
| 1. Unit tests | No | Free | No |
| 2. Read-only scan | Yes | Free | No |
| 3. Test environment | Yes | Cents per day | Creates one resource group |
| 4. Azure Policy | Yes | Free | Creates policy assignments |
| 5. Local Functions host | Yes | Free | No |
| 6. Teams report | Yes | Free | No |
| 7. Deploy | Yes | Low | Creates a Function App |

## Prerequisites
- Python 3.11 or later
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- An Azure subscription you own. A personal pay-as-you-go or free-trial subscription is recommended.
- For stage 5: [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) and [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite)

## 1. Unit tests (offline)
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -v
ruff check .
```
Expected: all tests pass. These use in-memory fakes, so no Azure access is involved.

## 2. Read-only scan against your subscription
```bash
az login
az account show --query "{name:name, id:id}" -o table   # confirm the right subscription
export GOV_SUBSCRIPTION_IDS=$(az account show --query id -o tsv)
python -m governance.cli -v --json report.json
```
This only reads inventory and metrics. It's safe to run against any subscription where you hold Reader, though the results depend on what already exists there.

Each scanner's query is the `KQL` string at the top of its module in `governance/scanners/`. Paste any of them into **Resource Graph Explorer** in the portal to see the raw rows.

## 3. Disposable test environment
```bash
./scripts/create-lab.sh           # creates rg-gov-lab with known issues
# wait about a minute for Resource Graph to index the new resources
python -m governance.cli -v
```
Expected findings in `rg-gov-lab`:

| Check | Resource | Severity |
|---|---|---|
| `orphaned-disk` | `orphan-disk-…` | Low |
| `orphaned-public-ip` | `pip-partial-…` | Low |
| `orphaned-nic` | `nic-orphan-…` | Low |
| `untagged-resource` | storage account, disk, NIC, VNet | Medium (no tags) |
| `untagged-resource` | `pip-partial-…` | Low (has `owner` only) |

If Azure Policy from stage 4 is already assigned, new resources inherit `owner` from the resource group, so untagged findings show as Low instead of Medium.

### Optional: stopped-but-allocated VM
Costs a few cents per hour while it exists.
```bash
az vm create -g rg-gov-lab -n vm-stopped --image Ubuntu2404 --size Standard_B1s \
  --admin-username azureuser --generate-ssh-keys --public-ip-address "" -o none
az vm stop -g rg-gov-lab -n vm-stopped       # stop WITHOUT deallocating
# wait about a minute
python -m governance.cli -v                  # expect stopped-not-deallocated-vm (High)
az vm deallocate -g rg-gov-lab -n vm-stopped # stops compute billing
```
Idle-VM detection needs at least 72 hours of CPU history, so a new VM won't appear as idle until then.

Clean up when you're done:
```bash
az group delete -n rg-gov-lab --yes --no-wait
```

## 4. Azure Policy
Start in audit mode, which evaluates compliance without blocking or changing anything:
```bash
ENFORCEMENT=DoNotEnforce ./scripts/apply-policy.sh
```
After about 30 minutes, open **Policy → Compliance** in the portal to see which resource groups and resources are non-compliant.

Then enforce:
```bash
./scripts/apply-policy.sh
```
This creates:
- a **Deny** assignment: resource groups must have an `owner` tag
- three **Modify** assignments: resources inherit `owner`, `environment` and `costCenter` from their resource group if missing, each with its own managed identity
- **remediation tasks** that apply the inherited tags to existing resources

Test the deny:
```bash
az group create -n rg-no-owner -l westus2          # should fail with RequestDisallowedByPolicy
az group create -n rg-with-owner -l westus2 --tags owner=you && az group delete -n rg-with-owner --yes
```

Check remediation progress with `az policy remediation list -o table`. Remove everything with `./scripts/remove-policy.sh`; tags already applied stay in place.

## 5. Local Azure Functions host
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

## 6. Teams report
1. In Teams, open **Workflows** and create a flow from a template that posts to a channel when a webhook request is received.
2. Copy the generated URL into `TEAMS_WEBHOOK_URL`. Treat it as a secret.
3. Run `python -m governance.cli --teams`.

## 7. Deploy
See `scripts/deploy.sh`. Run it a section at a time and check each resource in the portal before moving to the next.

## Cost safeguard
Before stage 3, create a budget alert on your subscription (**Cost Management**, then **Budgets**), for example $10 per month with email alerts at 50% and 100%.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| `DefaultAzureCredential failed to retrieve a token` | Not logged in. Run `az login`. |
| Scan returns no rows | Wrong subscription selected, or resources created less than a minute ago |
| `AuthorizationFailed` | The identity lacks Reader on the subscription |
| `RequestDisallowedByPolicy` when creating a resource group | Working as intended: add `--tags owner=<name>` |
| No idle VMs reported | VMs need at least 72 hours of metrics; lower `GOV_IDLE_MIN_HOURS` to test |
| `func start` fails on the timer trigger | Azurite isn't running |
