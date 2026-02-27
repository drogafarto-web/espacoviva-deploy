#!/bin/bash
# Kill any existing mpv to avoid audio overlap
killall -9 mpv 2>/dev/null || true
# Play from YouTube search
# Play from YouTube search with optimized cache for legacy hardware
mpv --no-video \
    --cache=yes \
    --demuxer-max-bytes=50M \
    --demuxer-readahead-secs=30 \
    --loop-playlist \
    --shuffle \
    --ytdl-format="bestaudio[ext=m4a]/bestaudio/best" \
    "ytdl://ytsearch:$*"

