#!/bin/bash
# visio-gpu-tunnel.sh - Run on the Mac, not on the cluster. Keeps the cluster's
# model-api gateway reachable at http://localhost:18012, whichever login node
# the gateway runs on.
#
# It runs in a loop:
#   1. Reads the gateway's node and port from gateway.host on the cluster
#      (gateway/run.sh writes it) and checks that the gateway answers.
#      If it does not, it asks the cluster to start it with gateway/ensure.sh,
#      at most once every 10 minutes and 3 times in a row. ensure.sh starts the
#      gateway only after checking from inside the cluster that it is down.
#   2. Opens an SSH tunnel: 127.0.0.1:18012 on this Mac -> that node and port.
#   3. Checks the gateway through the tunnel every 30 s. A tunnel busy with
#      uploads answers slowly, so a failed check is only a hint: a second ssh
#      connection then asks the cluster whether the gateway is fine. It closes
#      the tunnel and goes back to step 1 only when the tunnel's ssh has exited
#      (network drop, Mac woke from sleep), the gateway moved to another node,
#      or the gateway stopped answering twice in a row.
#
# It uses port 18012, not 8012, so Cursor's port forwarding can never take it.
# In VisioStudio, set Settings > GPU server URL to http://localhost:18012.
#
# Install as a background service (starts at login, restarted if it stops).
# macOS blocks background services from reading ~/Documents, so the script is
# copied out of the repo first. Run from the repo root:
#   mkdir -p ~/.local/bin
#   cp scripts/gpu-tunnel/visio-gpu-tunnel.sh ~/.local/bin/ && chmod +x ~/.local/bin/visio-gpu-tunnel.sh
#   cp scripts/gpu-tunnel/com.visiostudio.gpu-tunnel.plist ~/Library/LaunchAgents/
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.visiostudio.gpu-tunnel.plist
#
# Log:        tail -f ~/Library/Logs/visio-gpu-tunnel.log
# Restart:    launchctl kickstart -k gui/$(id -u)/com.visiostudio.gpu-tunnel
# Uninstall:  launchctl bootout gui/$(id -u)/com.visiostudio.gpu-tunnel
#             rm ~/Library/LaunchAgents/com.visiostudio.gpu-tunnel.plist
#
# To try it in a Terminal instead: ./scripts/gpu-tunnel/visio-gpu-tunnel.sh (Ctrl-C stops it).

# --- Settings ---------------------------------------------------------------
# The name you use to ssh into the cluster (the same one you use in Cursor).
CLUSTER_HOST="${CLUSTER_HOST:-AI-Cluster}"
# Where gateway/run.sh records "node port", on the cluster.
GATEWAY_FILE="${GATEWAY_FILE:-~/vision-data/gateway.host}"
# The port on this Mac that leads to the gateway.
LOCAL_PORT="${LOCAL_PORT:-18012}"
# 1 starts the gateway when it is not running, 0 only waits for someone to start it.
AUTO_START="${AUTO_START:-1}"
# The script on the cluster that starts the gateway only if it is down.
ENSURE_SCRIPT="${ENSURE_SCRIPT:-~/vision-models/gateway/ensure.sh}"
# -----------------------------------------------------------------------------

CHECK_INTERVAL_S=30
RETRY_DELAY_S=30
START_COOLDOWN_S=600
MAX_START_ATTEMPTS=3
# Checks in a row that fail through the tunnel while the gateway is fine before
# the tunnel is reopened anyway (10 x 30 s = 5 minutes).
MAX_SLOW_CHECKS=10
# Exit status of the lookup when the cluster answers but the gateway does not.
GATEWAY_DOWN=3
# BatchMode makes ssh fail instead of waiting for a password nobody can type.
# ssh closes a dead connection itself after 15 s x 6 = 90 s without an answer.
# The wait is long on purpose: big uploads can delay the answers for a while.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=6)

tunnel_pid=""
start_attempts=0
last_start_at=0
gave_up=0

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

# A sleep that a stop signal can interrupt (a plain sleep delays the trap until it ends).
pause() {
  sleep "$1" &
  wait $!
}

close_tunnel() {
  if [ -n "$tunnel_pid" ]; then
    kill "$tunnel_pid" 2>/dev/null
    wait "$tunnel_pid" 2>/dev/null
    tunnel_pid=""
  fi
}

trap 'close_tunnel; log "Stopped."; exit 0' INT TERM

# Prints "node port" and exits 0 when the gateway answers. Exits GATEWAY_DOWN
# when the cluster answers but the gateway does not, and 255 (ssh's own code)
# when the cluster cannot be reached.
find_gateway() {
  ssh "${SSH_OPTS[@]}" "$CLUSTER_HOST" "read -r node port _ 2>/dev/null < $GATEWAY_FILE; \
    port=\${port:-8012}; \
    [ -n \"\$node\" ] && curl -s -m 5 http://\$node:\$port/v1/health | grep -q '\"status\":\"ok\"' \
    && echo \"\$node \$port\" && exit 0; exit $GATEWAY_DOWN"
}

# Runs ensure.sh on the cluster unless auto-start is off, the last attempt was
# less than START_COOLDOWN_S ago, or MAX_START_ATTEMPTS in a row have failed.
# Returns 0 when it ran ensure.sh, 1 when it did not.
maybe_start_gateway() {
  [ "$AUTO_START" = "1" ] || return 1
  if [ "$start_attempts" -ge "$MAX_START_ATTEMPTS" ]; then
    if [ "$gave_up" != "1" ]; then
      log "Stopped trying to start the gateway after $MAX_START_ATTEMPTS attempts. Look at the messages above, fix the problem on the cluster and start it by hand: cd ~/vision-models && gateway/run.sh. The tunnel opens as soon as it answers."
      gave_up=1
    fi
    return 1
  fi
  local now
  now=$(date +%s)
  [ $((now - last_start_at)) -ge "$START_COOLDOWN_S" ] || return 1

  start_attempts=$((start_attempts + 1))
  last_start_at=$now
  log "Asking the cluster to start the gateway (attempt $start_attempts of $MAX_START_ATTEMPTS)."
  ssh "${SSH_OPTS[@]}" "$CLUSTER_HOST" "$ENSURE_SCRIPT" 2>&1 | while IFS= read -r line; do
    log "  cluster: $line"
  done
  return 0
}

local_port_in_use() {
  lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1
}

gateway_answers_through_tunnel() {
  curl -s -m 10 "http://127.0.0.1:$LOCAL_PORT/v1/health" | grep -q '"status":"ok"'
}

# A hard kill of this script (launchctl kickstart -k, kill -9) cannot run the
# trap, so the tunnel's ssh can stay behind and keep the port. At startup, close
# such a leftover. Only ssh processes that forward LOCAL_PORT are touched, and
# nothing is touched when another copy of this script is running.
close_leftover_tunnel() {
  local other_copies
  other_copies=$(pgrep -f "visio-gpu-tunnel.sh" | grep -vx "$$")
  [ -z "$other_copies" ] || return 0

  local pid command
  for pid in $(lsof -nP -t -iTCP:"$LOCAL_PORT" -sTCP:LISTEN 2>/dev/null); do
    command=$(ps -p "$pid" -o command= 2>/dev/null)
    case "$command" in
      ssh\ *"-L 127.0.0.1:$LOCAL_PORT:"*)
        log "Closing a leftover tunnel from an earlier run (ssh pid $pid)."
        kill "$pid" 2>/dev/null
        ;;
    esac
  done
  sleep 1
}

log "Starting. The gateway will be at http://localhost:$LOCAL_PORT"
close_leftover_tunnel

while true; do
  found=$(find_gateway)
  lookup_status=$?

  if [ "$lookup_status" -eq "$GATEWAY_DOWN" ]; then
    if maybe_start_gateway; then
      continue
    fi
    log "The gateway is not running (to start it by hand: cd ~/vision-models && gateway/run.sh). Checking again in ${RETRY_DELAY_S}s."
    pause "$RETRY_DELAY_S"
    continue
  fi

  read -r node port <<< "$found"
  if [ "$lookup_status" -ne 0 ] || ! [[ "$node" =~ ^[A-Za-z0-9._-]+$ && "$port" =~ ^[0-9]+$ ]]; then
    log "Could not reach $CLUSTER_HOST to look up the gateway (ssh exit $lookup_status). Trying again in ${RETRY_DELAY_S}s."
    pause "$RETRY_DELAY_S"
    continue
  fi

  if local_port_in_use; then
    log "Port $LOCAL_PORT on this Mac is in use by another program. Trying again in ${RETRY_DELAY_S}s."
    lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN
    pause "$RETRY_DELAY_S"
    continue
  fi

  ssh "${SSH_OPTS[@]}" -N -o ExitOnForwardFailure=yes \
    -L "127.0.0.1:$LOCAL_PORT:$node:$port" "$CLUSTER_HOST" &
  tunnel_pid=$!
  log "Tunnel open: localhost:$LOCAL_PORT -> $node:$port"
  start_attempts=0
  gave_up=0

  down_checks=0       # lookups in a row that found the gateway down
  slow_checks=0       # checks in a row that failed through the tunnel while the gateway was fine
  busy_logged=0
  reconnect_reason=""
  while kill -0 "$tunnel_pid" 2>/dev/null && [ -z "$reconnect_reason" ]; do
    pause "$CHECK_INTERVAL_S"
    if gateway_answers_through_tunnel; then
      down_checks=0
      slow_checks=0
      if [ "$busy_logged" = "1" ]; then
        log "The tunnel answers normally again."
        busy_logged=0
      fi
      continue
    fi

    # The check failed through the tunnel. Ask the cluster over a separate ssh connection.
    current=$(find_gateway)
    case $? in
      0)
        down_checks=0
        if [ "$current" != "$node $port" ]; then
          reconnect_reason="The gateway moved from $node:$port to ${current// /:}."
        else
          slow_checks=$((slow_checks + 1))
          if [ "$slow_checks" -ge "$MAX_SLOW_CHECKS" ]; then
            reconnect_reason="No answer through the tunnel for $((slow_checks * CHECK_INTERVAL_S)) s although the gateway is fine."
          elif [ "$busy_logged" = "0" ]; then
            log "No answer through the tunnel, but the gateway is fine on $node. Keeping the tunnel (it may be busy with uploads)."
            busy_logged=1
          fi
        fi
        ;;
      "$GATEWAY_DOWN")
        down_checks=$((down_checks + 1))
        if [ "$down_checks" -ge 2 ]; then
          reconnect_reason="The gateway stopped answering on $node."
        fi
        ;;
      *)
        # The cluster cannot be reached from here. If the connection is really
        # dead, ssh closes the tunnel itself and that ends this loop.
        ;;
    esac
  done

  if [ -z "$reconnect_reason" ]; then
    reconnect_reason="The tunnel closed (connection lost)."
  fi
  log "$reconnect_reason Reconnecting."
  close_tunnel
  pause 5
done
