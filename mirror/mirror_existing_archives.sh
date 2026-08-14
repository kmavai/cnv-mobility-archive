#!/usr/bin/env bash
# Mirror the two EXISTING public archives of Mobi supply-side history.
#
# Neither has any preservation commitment: one is git history in a single
# person's repository, the other is an endpoint its own maintainers label
# "experimental and subject to change". Mirroring both is a one-afternoon
# task that protects ~3 years of history you cannot otherwise recreate.
set -euo pipefail
DEST="${1:-./mirrors}"
mkdir -p "$DEST"

echo "==> 1/2  bike-sharing-history (MIT licensed; git history IS the archive)"
echo "         Vancouver/Mobi coverage: 2023-08-05 -> 2025-05-21, ~15 min"
echo "         Full repo is ~68GB (100+ systems). We only need one file's"
echo "         history, so this does a BLOBLESS + SPARSE clone: full commit"
echo "         history (do NOT shallow-clone, that would lose it), but only"
echo "         the Vancouver blob content, backfilled locally. ~800MB instead"
echo "         of 68GB, with identical git-log/git-show results for that path."
if [ ! -d "$DEST/bike-sharing-history" ]; then
  git clone --filter=blob:none --no-checkout \
    https://github.com/MaxHalford/bike-sharing-history.git \
    "$DEST/bike-sharing-history"
  git -C "$DEST/bike-sharing-history" sparse-checkout init --no-cone
  git -C "$DEST/bike-sharing-history" sparse-checkout set \
    data/stations/vancouver/mobi-bike-share.geojson
  git -C "$DEST/bike-sharing-history" backfill --sparse --min-batch-size=2000
else
  git -C "$DEST/bike-sharing-history" fetch --all
  git -C "$DEST/bike-sharing-history" backfill --sparse --min-batch-size=2000
fi

echo
echo "==> 2/2  CityBikes monthly Parquet dumps for network 'mobibikes'"
echo "         Coverage: 2024-11 -> present"
mkdir -p "$DEST/citybikes"
Y=2024; M=11
NOW_Y=$(date -u +%Y); NOW_M=$(date -u +%-m)
while [ "$Y" -lt "$NOW_Y" ] || { [ "$Y" -eq "$NOW_Y" ] && [ "$M" -le "$NOW_M" ]; }; do
  YM=$(printf "%04d%02d" "$Y" "$M")
  URL="https://data.citybik.es/dumps/by-network/${Y}/${YM}-mobibikes-stats.parquet"
  OUT="$DEST/citybikes/${YM}-mobibikes-stats.parquet"
  if [ ! -f "$OUT" ]; then
    printf "  %s ... " "$YM"
    if curl -fsSL --retry 3 -o "$OUT" "$URL"; then echo "ok"; else echo "not found"; rm -f "$OUT"; fi
  fi
  M=$((M+1)); if [ "$M" -gt 12 ]; then M=1; Y=$((Y+1)); fi
done

echo
echo "Done. Extract just the Vancouver series into a parquet with:"
echo "  cd ../03_data && source .venv/bin/activate"
echo "  python3 scripts/extract_vancouver_mirror.py"
echo "(that script streams every commit blob through one 'git cat-file --batch'"
echo " process -- doing it one 'git show' per commit is ~2 objects/sec even"
echo " after backfill, i.e. hours for the full history; batched is seconds)"
