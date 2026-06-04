#!/usr/bin/env bash
# Idempotently wire the Homepage container onto the shared `homepage` network so
# it can resolve one-piece-webapp by name. Safe to re-run; only acts when needed.
set -euo pipefail

NETWORK="${HOMEPAGE_NETWORK:-homepage}"
CONTAINER="${HOMEPAGE_CONTAINER:-valhalla-homepage}"

# 1. Network
if docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "✓ network '$NETWORK' already exists"
else
    docker network create "$NETWORK" >/dev/null
    echo "+ created network '$NETWORK'"
fi

# 2. Homepage container must exist to connect it
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "! container '$CONTAINER' not found — start Homepage, then re-run"
    echo "  (set HOMEPAGE_CONTAINER=<name> if it's named differently)"
    exit 1
fi

# 3. Attach the container if it isn't already on the network
if docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' \
        "$CONTAINER" | grep -qx "$NETWORK"; then
    echo "✓ '$CONTAINER' already on '$NETWORK' — nothing to do"
else
    docker network connect "$NETWORK" "$CONTAINER"
    echo "+ connected '$CONTAINER' to '$NETWORK'"
fi
