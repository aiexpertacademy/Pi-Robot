#!/bin/bash

echo "Starting Fast Robot Services for Raspberry Pi..."

# Cleanup trap to kill background processes when script exits
trap "echo 'Shutting down services...'; kill $BACKEND_PID; exit" SIGINT SIGTERM

# 1. Start Backend Agent
echo "[1/2] Starting Backend Agent..."
# Adjust the venv activation path if yours is different on the Pi:
source venv_stable/bin/activate
export MPLBACKEND=Agg
python3 agent.py dev &
BACKEND_PID=$!

# 2. Wait for initialization then launch Terminal Chat
echo "Waiting 5 seconds for backend to initialize..."
sleep 5
echo "[2/2] Starting Terminal Connection..."
python3 terminal_chat.py

# If the terminal chat exits, clean up the other processes automatically
kill $BACKEND_PID
