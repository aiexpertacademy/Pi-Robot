#!/bin/bash

echo "Starting Fast Robot Services for Raspberry Pi..."

# Cleanup trap to kill background processes when script exits
trap "echo 'Shutting down services...'; kill $BACKEND_PID $FRONTEND_PID; exit" SIGINT SIGTERM

# 1. Start Backend Agent
echo "[1/3] Starting Backend Agent..."
# Adjust the venv activation path if yours is different on the Pi:
source venv_stable/bin/activate
python3 agent.py dev &
BACKEND_PID=$!

# 2. Start Client UI (React Face)
echo "[2/3] Starting Client UI (Robot Face) on port 5173..."
cd client
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!
cd ..

# 3. Wait for initialization then launch Terminal Chat
echo "Waiting 5 seconds for backend to initialize..."
sleep 5
echo "[3/3] Starting Terminal Connection..."
python3 terminal_chat.py

# If the terminal chat exits, clean up the other processes automatically
kill $BACKEND_PID
kill $FRONTEND_PID
