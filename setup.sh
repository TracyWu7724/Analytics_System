#!/bin/bash

echo "Starting dev env..."

# Start backend
echo "Starting backend..."
uvicorn backend.services.api.agent:app --port 8000 --reload &

BACKEND_PID=$!

# Start frontend
echo "Starting frontend..."
cd frontend
npm start &

FRONTEND_PID=$!

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID