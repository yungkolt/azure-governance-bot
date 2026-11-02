# Roadmap

## Phase 1: Inventory and reporting (complete)
- Resource Graph client with paging
- Untagged-resource and orphaned-disk scanners
- Teams Adaptive Card reporting
- Timer and HTTP triggers on Azure Functions
- System-assigned Managed Identity with Reader
- CI: lint and tests on every push

## Phase 2: Waste detection and policy enforcement (complete)
- Scanners for orphaned public IPs and NICs, empty App Service Plans, and VMs that are stopped but not deallocated
- Idle-VM detection from Azure Monitor metrics (low average and low peak CPU over 14 days)
- `Clients` dependency container so scanners can use more than one data source
- Azure Policy: deny resource groups without `owner`, and inherit tags from the resource group (Modify effect), with remediation tasks for existing resources
- Audit-first rollout with `ENFORCEMENT=DoNotEnforce`
- Decision: no custom RBAC role. Reader covers metric reads, and all writes are made by Policy's own identities.

## Phase 3: Identity and access review (complete)
- Broad privileged role assignments at subscription, management-group or root scope, with direct-to-user assignments called out
- Stale role assignments held by deleted principals or disabled users, via Microsoft Graph
- Custom roles granting `*` or provider-wide wildcard actions
- Allowlist for break-glass and automation identities
- Graph permission script for the Managed Identity (`Directory.Read.All`, the least-privileged permission for `getByIds`)
- Identity lab script for producing each finding in a personal tenant
- Possible extension: last sign-in date for users (requires `AuditLog.Read.All` and Entra ID P1)

## Phase 4: Cost analytics (complete)
- Daily actual cost per resource group from the Cost Management Query API
- Anomaly detection: rolling mean and standard deviation with a minimum dollar threshold; new-spend detection
- Retail Prices API for stopped and idle VMs (Linux pay-as-you-go list price)
- Report history in Blob Storage, partitioned by date

## Phase 5: Production readiness (complete)
- Bicep for every resource and role assignment, deployed at subscription scope
- GitHub Actions deployment with OIDC workload identity federation (no stored secrets)
- Deployment identity constrained by a role-assignment condition
- Key Vault reference for the Teams webhook; storage with shared keys disabled
- Application Insights with failed-run and missed-run alerts
- CI validation of Bicep and shell scripts; post-deploy smoke test
- End-to-end test script against a real subscription with automatic cleanup

## Possible extensions
- Per-tier managed disk pricing from the Retail Prices API
- Week-over-week trend in the Teams card, read from report history
- Last sign-in date for users in the stale-assignment check (`AuditLog.Read.All`, Entra ID P1)
- Approval card in Teams before high-impact remediation
- Management-group scope for multi-subscription organizations
