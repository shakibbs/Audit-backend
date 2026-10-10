#!/bin/sh
# Updates CiV on the server: pulls both repos, rebuilds only CiV's containers, checks they answer.
# Installed once as /opt/civ/deploy.sh. GitHub Actions runs it through an SSH key that can run nothing else.
set -eu
exec 9>/opt/civ/.deploy.lock
flock -w 900 9  # one update at a time, even if both repos push together

echo "== pull =="
git -C /opt/civ/AUDIT pull --ff-only -q
git -C /opt/civ/Audit-backend pull --ff-only -q
git -C /opt/civ/AUDIT log --oneline -1
git -C /opt/civ/Audit-backend log --oneline -1

echo "== build and restart CiV (n8n untouched) =="
cd /opt/civ/Audit-backend/deploy
docker compose --env-file .env.production up -d --build --remove-orphans
docker image prune -f >/dev/null

echo "== check =="
# 127.0.0.1, not localhost: in the small Linux images "localhost" can resolve to IPv6, where the apps do not listen.
for i in $(seq 1 30); do
  if docker compose --env-file .env.production exec -T backend python -c "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/api/health', headers={'Host': 'backend'}), timeout=5)" 2>/dev/null \
     && docker compose --env-file .env.production exec -T portal wget -q -O /dev/null http://127.0.0.1:3000/sign-in 2>/dev/null; then
    docker compose --env-file .env.production ps
    echo "DEPLOY OK"
    exit 0
  fi
  sleep 4
done
docker compose --env-file .env.production logs --tail 40 backend portal
echo "DEPLOY FAILED: CiV did not answer after the update"
exit 1
