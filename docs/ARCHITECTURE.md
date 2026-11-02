# Architecture

## Components

```mermaid
flowchart TB
    subgraph Azure Function App
        TT[scheduled_scan<br/>timer trigger] --> RUN
        HT[scan_now<br/>HTTP trigger, function key] --> RUN
        RUN[runner.run_scan] --> REG[Scanner registry]
        REG --> SG[Inventory scanners<br/>untagged, disks, IPs,<br/>NICs, plans, stopped VMs]
        REG --> SI[idle_vms.py]
        REG --> SR[RBAC scanners<br/>broad, stale, wildcard]
        RUN --> TEAMS[reporting/teams.py]
    end
    MI[System-assigned<br/>Managed Identity] -. Reader .-> ARG
    MI -. Reader .-> MON
    MI -. Directory.Read.All .-> MSG[(Microsoft Graph)]
    SR --> ARG
    SR --> MSG
    REG --> SC[cost_anomalies.py]
    SC --> CM[(Cost Management)]
    SI --> RP[(Retail Prices API)]
    RUN --> HIST[reporting/history.py]
    HIST --> BLOB[(Blob Storage)]
    SG --> ARG[(Azure Resource Graph)]
    SI --> ARG
    SI --> MON[(Azure Monitor<br/>metrics API)]
    TEAMS --> WF[Teams Workflow webhook]
    CLI[governance.cli<br/>local] --> RUN

    subgraph Azure Policy
        DENY[Deny: RG requires owner]
        MOD[Modify: inherit tags<br/>own identities]
    end
```

## Request flow

1. A trigger fires: the timer on schedule, the HTTP endpoint on demand, or the CLI locally.
2. `load_settings()` reads configuration from environment variables.
3. `build_clients()` creates one `DefaultAzureCredential` and the clients that share it, in a `Clients` container.
4. `run_scan()` creates a `ScanReport` and calls each registered scanner with the container.
5. Inventory scanners send one KQL query each to Resource Graph and convert rows into `Finding` objects.
6. The idle-VM scanner queries Resource Graph for running VMs, then requests 14 days of hourly CPU for each VM from Azure Monitor.
7. The RBAC scanners read role assignments and definitions from Resource Graph's `authorizationresources` table, then resolve the principals through Microsoft Graph.
8. The cost-anomaly scanner reads daily cost per resource group from Cost Management; VM findings are priced from the Retail Prices API.
9. Findings are aggregated. An exception in one scanner, or in one VM's metrics call, is logged without stopping the rest.
10. If a storage URL is configured, the report is saved to Blob Storage. If a webhook is configured, an Adaptive Card summary is posted to Teams. The HTTP trigger also returns the full report as JSON.

## Prevent, then detect

Governance is split between Azure Policy and the scanner according to what each does best.

| Concern | Handled by | Mechanism |
|---|---|---|
| Resource group created without `owner` | Policy | **Deny** at create or update time |
| Resource missing tags its resource group has | Policy | **Modify** adds them on create or update; remediation tasks fix existing resources |
| Resource missing tags that its resource group lacks too | Scanner | `untagged-resource` |
| Orphaned, idle or stopped resources | Scanner | Waste checks |

Policy acts at the moment of change, so it stops problems from being created. It cannot judge whether a resource is *used*, so waste detection stays in the scanner. The result: Policy keeps the tagging standard enforced, and the scanner's untagged count trends toward zero while it continues to find waste.

`scripts/apply-policy.sh` supports `ENFORCEMENT=DoNotEnforce`, which evaluates compliance without denying or modifying anything. This is the standard way to roll out a new policy: measure the impact first, then enforce.

## Design rationale

### Resource Graph over ARM enumeration
Enumerating resources through ARM means one call per subscription, resource group and resource type, which is slow and hits ARM throttling limits. Resource Graph serves inventory from an index and handles cross-subscription queries in a single call. Results are paged at 1,000 rows, and `ResourceGraph.query()` follows `skip_token` until it has every row.

Trade-off: Resource Graph is eventually consistent, typically within a minute of a change. That is acceptable for a scheduled governance report.

Resource Graph also exposes properties not available from a plain resource listing, such as a VM's power state under `properties.extended.instanceView`, which the stopped-VM and idle-VM checks use.

### Identity and access
| Identity | Role | Used for |
|---|---|---|
| Function App system-assigned identity | Reader (subscription) | Resource Graph queries, metric reads |
| Function App system-assigned identity | `Directory.Read.All` (Microsoft Graph app role) | Resolving principals for the RBAC checks |
| Each Policy Modify assignment's identity | Roles declared by the policy definition | Writing inherited tags |
| Developer (local) | Your own `az login` session | Running the CLI |

`DefaultAzureCredential` resolves the Azure CLI session locally and the Managed Identity in Azure. Resource Graph returns only resources the caller can read, so scope is controlled by RBAC rather than application logic.

No custom RBAC role is needed. Reader already includes `Microsoft.Insights/metrics/read`, and the scanner never writes. Write access is held only by Policy's own identities, each scoped to one assignment. `apply-policy.sh` reads the required roles from the definition's `roleDefinitionIds` so the grant always matches what the policy needs. `POLICY_ROLE` can override it with a narrower role such as Tag Contributor.

### Dependency injection
Scanners take a `Clients` container instead of constructing SDK clients. The container holds `graph` (the `GraphQuery` protocol) and `metrics` (the `MetricsQuery` protocol). Tests inject `FakeGraph` and `FakeMetrics`, so the suite runs offline in milliseconds. Phase 3 (Microsoft Graph) and Phase 4 (Cost Management) add fields to the same container without changing existing scanners.

### Identity and access review
Three checks share one loader (`scanners/rbac.py`):

| Check | Finds | Why it matters |
|---|---|---|
| `broad-role-assignment` | Owner, Contributor, User Access Administrator or RBAC Administrator at subscription, management-group or root scope | Control over everything underneath; Owner and the two administrator roles can also grant access to others |
| `stale-role-assignment` | Assignments whose principal was deleted, or whose user is disabled | Deleted principals clutter access reviews and count toward the role-assignment limit; a disabled user's access returns the moment the account is re-enabled |
| `custom-role-wildcard` | Custom roles with `*` or `Provider/*` actions | Owner-equivalent power hidden behind an innocuous role name |

**Two permission systems.** Azure RBAC governs Azure resources; Microsoft Graph app roles govern directory data. They are granted separately. The Managed Identity's Reader role lets it *read* role assignments, but only a Graph app role (`Directory.Read.All`, granted by `scripts/grant-graph-permissions.sh`) lets it look up who the principals are. Locally, the Azure CLI's own token covers both.

**Matching roles to names.** Role assignments and role definitions are read in two Resource Graph queries and joined in Python on the role definition GUID. A KQL join is avoided because the two tables format `roleDefinitionId` differently, and built-in roles are not guaranteed to appear as rows. The GUIDs of the privileged built-in roles are fixed across every Azure tenant, so they are mapped directly. Because `ResourceGraph` caches results per query string within a run, the three checks cost two Resource Graph requests in total.

**Graph lookups.** `GraphDirectory` calls `directoryObjects/getByIds` (up to 1000 IDs per request) to learn which principals exist, then `users?$filter=id in (...)` (up to 15 IDs per filter) to read `accountEnabled`, which `getByIds` does not return by default. Results are cached for the run. Plain HTTPS is used rather than the Microsoft Graph SDK, which is large and asynchronous for what are two read-only calls.

**Failure modes.** A principal missing from the Graph response means it was deleted. A failed Graph *call* means nothing at all, so the stale check raises instead of reporting every assignment as stale, and the runner logs it. The broad-role check treats Graph as optional: it still reports, showing principal IDs instead of names. `ForeignGroup` principals (Azure Lighthouse) are skipped because they live in another tenant by design.

**Allowlisting.** Some identities legitimately need broad roles, such as break-glass accounts and automation identities. Their object IDs go in `GOV_RBAC_ALLOWED_PRINCIPALS`. A relevant example in this repository: if the Policy Modify definitions declare Contributor, the identities created by `apply-policy.sh` hold Contributor at subscription scope and are reported. The choices are to allowlist them, or to reapply with `POLICY_ROLE="Tag Contributor"` so they no longer hold a broad privileged role.

**Scope of the data.** Resource Graph returns the role assignments visible within the scanned subscriptions. Entra ID directory roles (such as Global Administrator) are a separate system and are not in scope, and neither are PIM *eligible* assignments, which are not standing access.

### Cost analytics
**Anomaly detection.** For each resource group, the most recent complete day of actual cost is compared with the previous 14 days:

> anomalous when `latest > mean + 3σ` **and** `latest − mean ≥ $5`

| Design choice | Reason |
|---|---|
| Standard deviation, not a fixed percentage | Adapts to each group: a volatile group needs a bigger jump than a steady one |
| Minimum dollar increase | A $0.10 group doubling to $0.20 is not worth anyone's attention |
| Missing days count as $0 | A group that suddenly starts spending is reported as *new spend* |
| Today is excluded | Cost data lags usage by roughly 8 to 24 hours, so today is always partial |
| Not counted as waste | An anomaly may be legitimate growth; severity reflects the cost if the jump became the new normal (increase × 30) |
| No machine learning | Two weeks of history, no labels, and every flag must be explainable in a sentence. Cost Management's own anomaly alerts exist; this check keeps findings in one report with visible, tested thresholds |

One Cost Management query per subscription returns daily `ActualCost` grouped by resource group. Reader is enough to read it. The Cost Management API is rate-limited more tightly than other ARM APIs, so the check never makes more than one call per subscription per run. Columns are parsed by name, not position, and both `Cost` and `PreTaxCost` are accepted because the column name differs by offer type.

**List prices.** Stopped and idle VMs are priced from the public Retail Prices API (no authentication) using the VM size and region. The price is the Linux pay-as-you-go rate, with Windows, Spot and Low Priority meters excluded. That's the floor of what the VM costs: Windows licensing adds to it, while reservations, savings plans and Azure Hybrid Benefit reduce it. Lookups are cached per run. If the API fails, the finding is still reported without a cost.

Disks, public IPs and App Service Plans keep static per-unit estimates. Managed disks are billed by size tier (P10, E10, S10…) rather than per GB, so an exact price requires mapping each disk to its tier; the estimate is sufficient for ranking.

**History.** Each report is saved as `reports/YYYY/MM/DD/<run_id>.json` in Blob Storage, so trends can be read by date prefix. The Function App's identity writes with Entra ID; the storage account has shared keys disabled.

### Idle-VM detection
A VM is idle when **both** hold over the lookback window:
- average CPU is below `GOV_IDLE_CPU_AVG` (5%)
- peak hourly CPU never exceeded `GOV_IDLE_CPU_MAX` (20%)

The peak condition prevents flagging a VM that is quiet all day but runs a heavy nightly job. VMs with fewer than `GOV_IDLE_MIN_HOURS` (72) of data are skipped so a newly created VM isn't judged on a few hours of history.

CPU alone cannot prove a VM is unneeded. A domain controller or licence server can be essential at 1% CPU. Idle findings are therefore recommendations to review, and nothing acts on them automatically.

Metrics come from the ARM metrics API through `azure-mgmt-monitor`. Platform metrics like `Percentage CPU` require no agent. (Metrics support was removed from `azure-monitor-query` in version 2.0.) The scanner makes one metrics call per running VM. That is fine for hundreds of VMs. Very large estates would move to the regional metrics batch API.

### Tag evaluation in Python
Azure tag names are case-insensitive, but Resource Graph returns them as stored. The untagged scanner retrieves tags and compares them case-insensitively in Python. Values that are only whitespace count as missing. At very large estates this filter could move into KQL to reduce payload size.

### Cost estimation
Disk, public IP and App Service Plan costs use static list-price tables to rank findings by impact. They are estimates and are labelled as such. Stopped VMs carry no estimate because VM pricing varies too widely by size, region and OS. Phase 4 replaces estimates with the Azure Retail Prices API and actual cost from Cost Management.

### Severity
Cost-based checks share one set of bands (`scanners/_common.py`): **High** ≥ $50/month, **Medium** ≥ $10/month, **Low** < $10/month.

| Check | Severity rule |
|---|---|
| Orphaned disk, public IP, empty App Service Plan | Cost bands |
| Orphaned NIC | Medium if it still holds a public IP, otherwise Low |
| Stopped but not deallocated VM | Always High (full compute cost for no work) |
| Idle VM | Medium (needs human review) |
| Untagged resource | Medium if missing all required tags, Low if missing some |
| Broad role assignment | High for Owner, User Access Administrator, RBAC Administrator; Medium for Contributor |
| Stale role assignment | High if the role is privileged, otherwise Medium |
| Custom role wildcard | High for `*`, Medium for a provider-wide wildcard |

## Security considerations
- No secrets in source or app settings. The Teams webhook URL is intended to be a Key Vault reference.
- The HTTP trigger requires a function key (`AuthLevel.FUNCTION`).
- The webhook client rejects non-HTTPS URLs.
- The scanner is read-only in both Azure and Microsoft Graph. Write access lives only with Policy assignment identities.
- Lab scripts that create test users give them random passwords that are never displayed, and the persistent one is disabled.

## Hosting
Azure Functions Flex Consumption: scales to zero and bills per execution, which suits a job that runs for seconds once a day. The function timeout is 10 minutes (`host.json`). Python dependencies are built remotely during deployment.

## Infrastructure and delivery
All infrastructure is Bicep (`infra/`), deployed at subscription scope because the scanner's Reader role is granted on the subscription itself. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full resource list.

| Concern | Approach |
|---|---|
| Pipeline authentication | OIDC workload identity federation; the federated credential trusts only the `production` environment of this repository |
| Pipeline authorization | Contributor plus Role Based Access Control Administrator, constrained by a role-assignment condition to the three roles the template grants |
| App secrets | Teams webhook in Key Vault, resolved by a Key Vault reference using the app's identity |
| Storage access | Managed identity only; `allowSharedKeyAccess: false` |
| Validation | CI lints and builds the Bicep and shellchecks every script on each pull request |
| Post-deploy check | The pipeline calls `/api/scan` and fails if the app doesn't return a report |
| Monitoring | Alerts on any failed invocation and on two days without a successful scheduled scan |

The scanner checks its own deployment. The pipeline's broad roles appear in `broad-role-assignment` unless it is allowlisted, which the setup script does explicitly. Its RBAC Administrator assignment carries a condition limiting which roles it can grant, so even when it isn't allowlisted it is reported at medium rather than high severity: a constrained delegate can't grant itself or anyone else arbitrary access. If the resource group is deleted without removing the subscription-level Reader assignment, the next scan from any other deployment reports it as a stale assignment.
