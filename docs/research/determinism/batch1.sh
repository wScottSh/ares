bash "$(dirname "$0")/run.sh" A1 --frames 3600 &
bash "$(dirname "$0")/run.sh" A2 --frames 3600 &
bash "$(dirname "$0")/run.sh" B1 --frames 3600 --entropy off &
sleep 3
bash "$(dirname "$0")/run.sh" B2 --frames 3600 --entropy off &
bash "$(dirname "$0")/run.sh" D1 --frames 3600 --cpu recompiler &
bash "$(dirname "$0")/run.sh" D2 --frames 3600 --cpu recompiler &
bash "$(dirname "$0")/run.sh" C2 --frames 3600 --rdp vulkan &
wait
