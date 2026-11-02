# Roadmap

## Phase 1: Inventory and reporting (complete)
- Resource Graph client with paging
- Untagged-resource and orphaned-disk scanners
- Teams Adaptive Card reporting
- Timer and HTTP triggers on Azure Functions
- System-assigned Managed Identity with Reader
- CI: lint and tests on every push

## Phase 2: Waste detection and policy enforcement
- Scanners for orphaned public IPs and NICs, empty App Service Plans, and VMs that are stopped but not deallocated
- Idle-VM detection from Azure Monitor metrics (sustained low CPU over 14 days)
- Azure Policy: deny resource groups without `owner`, and inherit tags from the resource group (modify effect), with remediation tasks for existing resources
- Custom RBAC role granting only the actions required for remediation

## Phase 3: Identity and access review
- Role-assignment scanner: Owner or Contributor at subscription or management-group scope, direct user assignments, and custom roles with wildcard actions
- Microsoft Graph integration to resolve principals and flag disabled or deleted identities that still hold role assignments
- Least-privilege Graph application permissions (`User.Read.All`, `Group.Read.All`)

## Phase 4: Cost analytics
- Daily cost by resource group from the Cost Management Query API
- Statistical anomaly detection (rolling mean and standard deviation)
- Azure Retail Prices API replacing static price estimates
- Historical reports stored in Blob Storage for trend analysis

## Phase 5: Production readiness
- Infrastructure as code (Bicep or Terraform) for every resource, role assignment and policy assignment
- GitHub Actions deployment with OIDC workload identity federation (no stored secrets)
- Key Vault references for configuration secrets
- Application Insights dashboards and alerts on failed runs
- Approval workflow in Teams for high-impact remediation
