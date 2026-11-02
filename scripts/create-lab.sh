#!/usr/bin/env bash
# Create a low-cost test environment containing known governance issues.
# Cost: a 4 GB Standard HDD disk + an empty storage account ~ a few cents/month.
# Delete everything with:  az group delete -n rg-gov-lab --yes
set -euo pipefail

RG=rg-gov-lab
LOC=${LOC:-westus2}
SUFFIX=$RANDOM

az group create -n "$RG" -l "$LOC" -o none

# 1) Orphaned disk: created standalone, never attached to a VM
az disk create -g "$RG" -n "orphan-disk-$SUFFIX" --size-gb 4 --sku Standard_LRS -o none

# 2) Untagged storage account
az storage account create -g "$RG" -n "stgovlab$SUFFIX" --sku Standard_LRS -o none

# 3) Partially tagged resource (has owner, missing environment/costCenter)
az network public-ip create -g "$RG" -n "pip-partial-$SUFFIX" --sku Standard \
  --tags owner=platform-team -o none

echo "Lab ready in $RG. Wait ~1 minute for Resource Graph to index, then run:"
echo "  python -m governance.cli -v"
