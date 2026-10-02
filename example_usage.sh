#!/bin/bash

# Example usage scripts for different scenarios

# 1. Basic usage - last 3 months
# python3 fetch_mitigated_findings.py --from 2024-07-01 --to 2024-09-30

# 2. Skip annotations for faster processing
# python3 fetch_mitigated_findings.py --from 2024-07-01 --to 2024-09-30 --skip-annotations

# 3. Larger page size for faster pagination (uses more memory)
# python3 fetch_mitigated_findings.py --from 2024-07-01 --to 2024-09-30 --size 2000

# 4. Custom output directory
# python3 fetch_mitigated_findings.py --from 2024-07-01 --to 2024-09-30 --out ~/veracode-reports/sept-2024

# 5. Long timeout for large result sets
# python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-09-30 --poll-timeout 1200

# Before running any of these:
# 1. Export your Veracode API credentials:
#    export VERACODE_API_KEY_ID="your_key_id"
#    export VERACODE_API_KEY_SECRET="your_key_secret"
#
# 2. Ensure httpie is installed with veracode_hmac plugin:
#    pip install httpie
#    http --plugins
#    (look for veracode_hmac in the list)
