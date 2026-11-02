#!/usr/bin/env bash
# Create a low-cost test environment containing known governance issues.
# Cost: a 4 GB Standard HDD disk, an empty storage account and an unassociated
# Standard public IP, roughly $4/month if left running; delete it when done.
# The virtual network and NIC are free.
#   Delete everything with:  az group delete -n rg-gov-lab --yes
set -euo pipefail

RG=rg-gov-lab
LOC=${LOC:-westus2}
SUFFIX=$RANDOM

# The resource group carries only `owner`, so it passes the deny policy in
# apply-policy.sh while its resources still have tagging gaps to find.
az group create -n "$RG" -l "$LOC" --tags owner=platform-team -o none

# 1) Orphaned disk: created standalone, never attached to a VM
az disk create -g "$RG" -n "orphan-disk-$SUFFIX" --size-gb 4 --sku Standard_LRS -o none

# 2) Untagged storage account
az storage account create -g "$RG" -n "stgovlab$SUFFIX" --sku Standard_LRS -o none

# 3) Unassociated Standard public IP, partially tagged
#    (has owner, missing environment and costCenter)
az network public-ip create -g "$RG" -n "pip-partial-$SUFFIX" --sku Standard \
  --zone 1 2 3 --tags owner=platform-team -o none

# 4) Orphaned NIC in a free virtual network
az network vnet create -g "$RG" -n vnet-lab --address-prefix 10.20.0.0/16 \
  --subnet-name default --subnet-prefix 10.20.0.0/24 -o none
az network nic create -g "$RG" -n "nic-orphan-$SUFFIX" --vnet-name vnet-lab \
  --subnet default -o none

echo "Lab ready in $RG. Wait about a minute for Resource Graph to index, then run:"
echo "  python -m governance.cli -v"
