pids=""
for i in $(seq 12); do python -c "while True: pass" & pids="$pids $!"; done
bash "$(dirname "$0")/run.sh" G3 --frames 3600 --no-runahead --rdp vulkan &
bash "$(dirname "$0")/run.sh" C3 --frames 3600 --rdp vulkan &
bash "$(dirname "$0")/run.sh" A3 --frames 3600 &
bash "$(dirname "$0")/run.sh" D3 --frames 3600 --cpu recompiler &
wait $(jobs -p | grep -v -w -F "$(echo $pids | tr ' ' '\n')") 2>/dev/null
for j in G3 C3 A3 D3; do until grep -q '^probe' $j.err 2>/dev/null; do sleep 2; done; done
kill $pids
echo done
