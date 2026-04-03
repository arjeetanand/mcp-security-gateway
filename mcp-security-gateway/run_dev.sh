#!/bin/bash

# Configuration and Environment
export PROJECT_ROOT=$(pwd)
export VENV_BIN="$PROJECT_ROOT/.venv/bin"

# Server 1: Sample MCP Server
export SAMPLE_SERVER_PORT=18090

# Server 2: Security Gateway
export GATEWAY_PORT=18080
export UPSTREAM_SERVERS_FILE="$PROJECT_ROOT/config/upstreams.local.json"
export TOOL_POLICY_FILE="$PROJECT_ROOT/config/tool_policies.json"
export DATABASE_PATH="$PROJECT_ROOT/data/gateway.local.db"
export OPA_URL=""
export ENABLE_FALLBACK_POLICY_ENGINE="true"

echo "==== Starting MCP Security Gateway Local stack ===="

# Ensure data directory exists
mkdir -p "$PROJECT_ROOT/data"

# Function to kill background processes on exit
cleanup() {
    echo ""
    echo "Shutting down servers..."
    kill $SAMPLE_PID 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

echo "-> Starting Sample MCP Server on port $SAMPLE_SERVER_PORT..."
cd "$PROJECT_ROOT/sample_server"
"$VENV_BIN/python" -m uvicorn app:app --host 127.0.0.1 --port $SAMPLE_SERVER_PORT > /tmp/sample_server.log 2>&1 &
SAMPLE_PID=$!

# Wait a moment for the sample server to start
sleep 2

echo "-> Starting Security Gateway on port $GATEWAY_PORT..."
cd "$PROJECT_ROOT/gateway"
"$VENV_BIN/python" -m uvicorn app.main:app --host 127.0.0.1 --port $GATEWAY_PORT
