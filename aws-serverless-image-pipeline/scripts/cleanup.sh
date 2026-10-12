#!/usr/bin/env bash
# Empty the buckets and delete the stack so nothing keeps billing.
# Usage: ./scripts/cleanup.sh [stack-name] [region]
set -euo pipefail

STACK="${1:-image-pipeline}"
REGION="${2:-us-east-1}"

for key in SourceBucketName ProcessedBucketName WebBucketName; do
  bucket=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text 2>/dev/null || true)
  if [[ -n "$bucket" && "$bucket" != "None" ]]; then
    echo "==> Emptying s3://$bucket"
    aws s3 rm "s3://$bucket" --recursive --region "$REGION"
  fi
done

echo "==> Deleting stack $STACK"
sam delete --stack-name "$STACK" --region "$REGION" --no-prompts
echo "Done."
