#!/bin/sh
cd "$(dirname "$0")" && exec python3 video_processor.py serve "$@"
