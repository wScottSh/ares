#!/usr/bin/env bash
# usage: matrix3.sh REPS LOG ; interleaves configs3.txt, waits for a quiet host before each run
cd /c/Users/Scott/n64-timing/m9
busy() { l=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).LoadPercentage" | tr -d " "); [ "${l:-100}" -gt 20 ] && echo 1 || echo 0; }
for r in $(seq ${3:-1} $1); do
  while IFS='|' read -r label envs exe args; do
    [ -z "$label" ] && continue
    waited=0
    while [ "$(busy)" -gt 0 ] && [ $waited -lt 30 ]; do sleep 2; waited=$((waited+2)); done
    q=$([ "$(busy)" -eq 0 ] && echo quiet || echo busy)
    row=$(./bench.sh "x3-$label-r$r" "$envs" ./$exe $args)
    echo "$row	$q" >> "$2"
  done < configs3.txt
done
