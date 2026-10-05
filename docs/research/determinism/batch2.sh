# Run from an empty results directory. batch2 expects saveX/ and saveY/ holding random 128 KiB "Nintendo 64/Legend of Zelda - Majora's Mask.flash" files.
N64RUN_FILL=0xA5 bash "$(dirname "$0")/run.sh" F1 --frames 3600 &
N64RUN_FILL=0x5A bash "$(dirname "$0")/run.sh" F2 --frames 3600 &
bash "$(dirname "$0")/run.sh" G1 --frames 3600 --no-runahead &
bash "$(dirname "$0")/run.sh" G2 --frames 3600 --no-runahead --rdp vulkan &
bash "$(dirname "$0")/run.sh" H1 --frames 3600 --save-dir "$PWD/saveX/" &
bash "$(dirname "$0")/run.sh" H2 --frames 3600 --save-dir "$PWD/saveY/" &
wait
