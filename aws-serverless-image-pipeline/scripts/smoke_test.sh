#!/usr/bin/env bash
# End-to-end check against a deployed stack: request URL -> upload -> wait for COMPLETED.
# Usage: ./scripts/smoke_test.sh <image-file> [stack-name] [region]
set -euo pipefail

FILE="${1:?usage: smoke_test.sh <image-file> [stack] [region]}"
STACK="${2:-image-pipeline}"
REGION="${3:-us-east-1}"

API=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
WEB=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='WebAppUrl'].OutputValue" --output text)

case "${FILE,,}" in
  *.png) TYPE=image/png ;; *.webp) TYPE=image/webp ;; *.gif) TYPE=image/gif ;; *) TYPE=image/jpeg ;;
esac

echo "==> Requesting upload URL"
RESP=$(curl -sf -X POST "$API/uploads" -H 'content-type: application/json' \
  -d "{\"filename\":\"$(basename "$FILE")\",\"contentType\":\"$TYPE\"}")
IMAGE_ID=$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["imageId"])')
URL=$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["upload"]["url"])')
FORM_ARGS=$(echo "$RESP" | python3 -c '
import sys, json, shlex
for k, v in json.load(sys.stdin)["upload"]["fields"].items():
    print("-F", shlex.quote(f"{k}={v}"), end=" ")')

echo "==> Uploading $FILE as $IMAGE_ID"
eval curl -sf -o /dev/null "$FORM_ARGS" -F "file=@$FILE" "$URL"

echo "==> Waiting for the pipeline"
for _ in $(seq 1 30); do
  sleep 2
  STATUS=$(curl -sf "$API/images/$IMAGE_ID" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
  echo "    $STATUS"
  case "$STATUS" in
    COMPLETED) echo "Thumbnail: $WEB/images/$IMAGE_ID/thumbnail.jpg"; echo "Full-res : $WEB/images/$IMAGE_ID/full.jpg"; exit 0 ;;
    FAILED|REJECTED) curl -s "$API/images/$IMAGE_ID"; echo; exit 1 ;;
  esac
done
echo "Timed out"; exit 1
