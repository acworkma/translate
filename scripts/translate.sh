#!/usr/bin/env bash
# Translate one or more DOCX files end-to-end via the deployed function app.
#
# Usage:
#   scripts/translate.sh -l es file1.docx [file2.docx ...]
#   scripts/translate.sh -l zh-Hans -j my-job-id ./report.docx
#   scripts/translate.sh -l es -o ./out/ docs/*.docx
#
# Flags:
#   -l LANG    target language (required). One of SUPPORTED_LANGUAGES app setting.
#   -j JOBID   job id prefix. Default: auto-generated from filename + epoch.
#   -o DIR     local output dir for downloaded translations. Default: ./translated/
#   -g RG      resource group. Default: rg-translate
#   -f APP     function app name. Default: func-translate-topmsk
#   -s STG     storage account name. Default: sttranslatetopmsk
#   -t SECS    poll timeout in seconds. Default: 600.
#   -k         keep going on per-file errors instead of exiting.
#   -h         show this help.
set -euo pipefail

LANG_CODE=""; JOB_PREFIX=""; OUT_DIR="./translated"
RG="rg-translate"; APP="func-translate-topmsk"; STG="sttranslatetopmsk"
TIMEOUT=600; KEEP_GOING=0

usage() { sed -n '2,20p' "$0"; exit "${1:-0}"; }

while getopts ":l:j:o:g:f:s:t:kh" opt; do
  case "$opt" in
    l) LANG_CODE="$OPTARG" ;;
    j) JOB_PREFIX="$OPTARG" ;;
    o) OUT_DIR="$OPTARG" ;;
    g) RG="$OPTARG" ;;
    f) APP="$OPTARG" ;;
    s) STG="$OPTARG" ;;
    t) TIMEOUT="$OPTARG" ;;
    k) KEEP_GOING=1 ;;
    h) usage 0 ;;
    \?) echo "unknown flag: -$OPTARG" >&2; usage 2 ;;
    :)  echo "flag -$OPTARG requires an argument" >&2; usage 2 ;;
  esac
done
shift $((OPTIND - 1))

[[ -z "$LANG_CODE" ]] && { echo "ERROR: -l <lang> is required" >&2; usage 2; }
[[ $# -lt 1 ]] && { echo "ERROR: pass at least one .docx file" >&2; usage 2; }

mkdir -p "$OUT_DIR"

echo "fetching function key..."
KEY=$(az functionapp keys list -g "$RG" -n "$APP" --query functionKeys.default -o tsv)
HOST="https://${APP}.azurewebsites.net"

submit_one() {
  local src="$1" total="$2"
  local base jid
  base=$(basename "$src" .docx | tr -c 'A-Za-z0-9-' '-' | sed 's/--*/-/g; s/^-//; s/-$//')
  if [[ "$total" -gt 1 || -z "$JOB_PREFIX" ]]; then
    jid="${JOB_PREFIX:+${JOB_PREFIX}-}${base}-$(date +%s)"
  else
    jid="$JOB_PREFIX"
  fi
  jid=${jid:0:60}

  echo ""
  echo "=== $src ==="
  echo "jobId=$jid lang=$LANG_CODE"

  az storage blob upload \
    --account-name "$STG" --auth-mode login \
    -c inbound -n "$jid/source.docx" -f "$src" \
    --overwrite --only-show-errors -o none

  local http
  http=$(curl -sS -X POST "$HOST/api/jobs?code=$KEY" \
    -H "Content-Type: application/json" \
    -d "{\"jobId\":\"$jid\",\"sourceBlob\":\"inbound/$jid/source.docx\",\"targetLanguage\":\"$LANG_CODE\"}" \
    -o /dev/null -w "%{http_code}")
  if [[ "$http" != "202" ]]; then
    echo "  start failed: HTTP $http" >&2
    return 1
  fi
  echo "  started (HTTP 202), polling..."

  local elapsed=0 state="" resp=""
  while (( elapsed < TIMEOUT )); do
    sleep 10; elapsed=$((elapsed + 10))
    resp=$(curl -sS "$HOST/api/jobs/$jid?code=$KEY")
    state=$(echo "$resp" | python3 -c "import json,sys;print(json.load(sys.stdin).get('runtimeStatus','?'))" 2>/dev/null || echo "?")
    printf "    [%ds] %s\n" "$elapsed" "$state"
    [[ "$state" == "Completed" || "$state" == "Failed" || "$state" == "Terminated" ]] && break
  done

  if [[ "$state" != "Completed" ]]; then
    echo "  job did not complete (state=$state)" >&2
    echo "$resp" | python3 -m json.tool >&2 || true
    return 1
  fi

  local out_status
  out_status=$(echo "$resp" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('output',{}).get('status','?'))")
  echo "  status=$out_status"

  if [[ "$out_status" == "completed" ]]; then
    local dest="$OUT_DIR/${jid}.docx"
    az storage blob download \
      --account-name "$STG" --auth-mode login \
      -c final -n "$jid/$LANG_CODE/source.docx" -f "$dest" \
      --overwrite --only-show-errors -o none
    echo "  -> $dest"
  elif [[ "$out_status" == "needs_review" ]]; then
    local dest="$OUT_DIR/${jid}.review.json"
    az storage blob download \
      --account-name "$STG" --auth-mode login \
      -c reviewed -n "$jid/review.json" -f "$dest" \
      --overwrite --only-show-errors -o none
    echo "  needs human review -> $dest"
  else
    echo "  unexpected output status; full response:" >&2
    echo "$resp" | python3 -m json.tool >&2
    return 1
  fi
}

rc=0
total=$#
for f in "$@"; do
  if [[ ! -f "$f" ]]; then
    echo "skip: $f (not a file)" >&2
    (( KEEP_GOING )) || exit 1
    rc=1; continue
  fi
  if ! submit_one "$f" "$total"; then
    (( KEEP_GOING )) || exit 1
    rc=1
  fi
done

exit $rc
