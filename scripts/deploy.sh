#!/usr/bin/env bash
# Build & deploy the stack, then publish the frontend.
# Usage: ./scripts/deploy.sh [stack-name] [region] [notification-email]
set -euo pipefail

STACK="${1:-image-pipeline}"
REGION="${2:-us-east-1}"
EMAIL="${3:-}"

if [[ "$STACK" =~ [A-Z] ]]; then
  echo "Stack name must be lowercase (it is used in an S3 bucket name)." >&2; exit 1
fi

cd "$(dirname "$0")/.."

echo "==> Building (container build so Pillow matches the Lambda runtime)"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  sam build --use-container
else
  echo "    Docker not available - building natively (fine on Linux x86_64)"
  sam build
fi

echo "==> Deploying stack '$STACK' to $REGION"
sam deploy \
  --stack-name "$STACK" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides "NotificationEmail=$EMAIL"

out() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
API_URL=$(out ApiUrl)
WEB_BUCKET=$(out WebBucketName)
DIST_ID=$(out DistributionId)
WEB_URL=$(out WebAppUrl)

echo "==> Publishing frontend to s3://$WEB_BUCKET"
TMP=$(mktemp -d)
cp frontend/index.html "$TMP/"
printf 'window.APP_CONFIG = { apiUrl: "%s" };\n' "$API_URL" > "$TMP/config.js"
aws s3 sync "$TMP" "s3://$WEB_BUCKET" --delete --region "$REGION"
rm -rf "$TMP"

aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/index.html" "/config.js" >/dev/null

echo
echo "Done."
echo "  Web app : $WEB_URL"
echo "  API     : $API_URL"
if [[ -n "$EMAIL" ]]; then echo "  Confirm the SNS subscription e-mail sent to $EMAIL."; fi
