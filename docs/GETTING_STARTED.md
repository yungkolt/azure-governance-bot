# Getting started

## Quick path: the full test run
```bash
az login && pip install -r requirements-dev.txt
./scripts/e2e.sh
```
`e2e.sh` runs the unit tests, lint and template checks, takes a baseline scan, creates both test environments, rescans until every expected finding appears, prints PASS or FAIL for each, and **always** deletes what it created, even if it fails or you press Ctrl-C. It takes 5 to 10 minutes and costs a few cents. `SKIP_RBAC=1` skips the identity lab if you don't have User Administrator rights.

The stages below do the same thing by hand, one moving part at a time, which is the better way to learn what each check does.

## Stages

| Stage | Needs Azure | Cost | Changes anything in Azure |
|---|---|---|---|
| 1. Unit tests | No | Free | No |
| 2. Read-only scan | Yes | Free | No |
| 3. Test environment | Yes | Cents per day | Creates one resource group |
| 4. Azure Policy | Yes | Free | Creates policy assignments |
| 5. Identity lab | Yes | Free | Creates test users, a role assignment and a custom role |
| 6. Local Functions host | Yes | Free | No |
| 7. Teams report | Yes | Free | No |
| 8. Cost anomalies | Yes | Free | No |
| 9. Deploy | Yes | Low | Creates the full stack from Bicep |

## Prerequisites
- Python 3.11 or later
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- An Azure subscription you own. A personal pay-as-you-go or free-trial subscription is recommended.
- For stage 5: User Administrator or Global Administrator in your own tenant
- For stage 6: [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local) and [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite)

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

## 5. Identity lab
```bash
./scripts/create-rbac-lab.sh
# wait a few minutes for Resource Graph to index role changes
python -m governance.cli -v
```
Expected findings:

| Check | Principal or role | Severity |
|---|---|---|
| `broad-role-assignment` | disabled lab user, Contributor at subscription | Medium |
| `stale-role-assignment` | disabled lab user (Contributor) | High |
| `stale-role-assignment` | deleted lab user (Reader), shown by object ID | Medium |
| `custom-role-wildcard` | `Gov Lab Compute Operator …` (`Microsoft.Compute/*`) | Medium |

You will also see a `broad-role-assignment` for **your own account** (Owner at subscription scope). That is accurate: subscription owners are exactly what the check is meant to surface. In an organization, the answer is to keep only a few owners, assign roles to groups, and use PIM for just-in-time elevation. In a personal subscription, you can allowlist yourself:
```bash
export GOV_RBAC_ALLOWED_PRINCIPALS=$(az ad signed-in-user show --query id -o tsv)
```
If you applied Azure Policy in stage 4, its Modify identities may also appear with Contributor. See *Allowlisting* in `ARCHITECTURE.md`.

Clean up:
```bash
./scripts/remove-rbac-lab.sh
```

## 6. Local Azure Functions host
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

## 7. Teams report
The report is posted through a Teams Workflows webhook. Office 365 Connectors (the older "Incoming Webhook") are being retired, so use Workflows.

1. In Teams, open the channel that should receive the report.
2. Select **...** (More options) next to the channel name, then **Workflows**.
3. Search for the template **Send webhook alerts to a channel** and select it.
4. Confirm the team and channel, then select **Save** (or **Add workflow**).
5. Select **Copy webhook link**.
6. Set the URL locally, then run a scan that posts:

   ```bash
   export TEAMS_WEBHOOK_URL='<copied URL>'   # PowerShell: $env:TEAMS_WEBHOOK_URL='<copied URL>'
   python -m governance.cli --teams
   ```

Treat the URL as a secret: anyone who has it can post to the channel. In the deployed app it lives in Key Vault (see [DEPLOYMENT.md](DEPLOYMENT.md)). If the workflow is turned off or deleted, posts fail and the failure is logged without stopping the scan.

## 8. Cost anomalies
The `cost-anomaly` check reads real billing data, so it can't be demonstrated instantly with a test environment: cost data arrives 8 to 24 hours after usage, and a baseline needs days of history. What you can do now:

```bash
python -m governance.cli -v              # look for the cost-anomaly line in the log
```
- `cost-anomaly: 0 findings` with no warning means the query worked and your spend is steady.
- To see the detection logic on known data, read `tests/test_cost_anomalies.py`, which covers spikes, noisy groups, new spend and small changes.
- To see a real anomaly, leave something moderately expensive running for a day in a resource group that normally costs little, wait a day for the data, and scan. Delete it afterwards.

## 9. Deploy
See [DEPLOYMENT.md](DEPLOYMENT.md): from your machine with `scripts/deploy.sh`, or from GitHub Actions with OIDC. Both use the same Bicep template.

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
| `Scanner stale-role-assignment failed` with 403 | The identity lacks Microsoft Graph access; run `grant-graph-permissions.sh` |
| RBAC lab findings missing | Role changes can take several minutes to reach Resource Graph |
| `Scanner cost-anomaly failed` with 429 | Cost Management throttling; it clears within minutes |
| `Scanner cost-anomaly failed` with 401 or 403 | The offer type doesn't expose cost data through the API (some sponsored or legacy offers), or the identity lacks Reader |
| `e2e.sh` times out | Resource Graph is slow to index; rerun with `TIMEOUT=900` |
| `func start` fails on the timer trigger | Azurite isn't running |
