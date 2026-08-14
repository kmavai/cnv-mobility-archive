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
echo "         Full clone - the history is the point, so do NOT shallow-clone."
if [ ! -d "$DEST/bike-sharing-history" ]; then
  git clone https://github.com/MaxHalford/bike-sharing-history.git \
    "$DEST/bike-sharing-history"
else
  git -C "$DEST/bike-sharing-history" fetch --all
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
echo "Done. Extract just the Vancouver series from the git history with:"
echo "  cd $DEST/bike-sharing-history"
echo "  git log --format='%H %aI' -- data/stations/vancouver/mobi-bike-share.geojson"
echo "  git show <sha>:data/stations/vancouver/mobi-bike-share.geojson"
