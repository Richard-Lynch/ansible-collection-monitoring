#!/usr/bin/env bash
#
# Emits Docker container health as Prometheus metrics, for node_exporter's textfile collector.
#
# WHY THIS EXISTS. cAdvisor (vendored into Alloy) already emits `container_health_state`, so this
# looks redundant. It is not: inside a Proxmox LXC guest cAdvisor cannot resolve a cgroup to a
# container (EPERM reading Docker's layerdb), so it DISCARDS every real container and emits only
# LXC-level cgroups.
#
# The consequence is not "missing data", it is WORSE: `container_health_state` exists, carries no
# `name` label, and reads 0 for every series — including for a container that has been unhealthy
# for hours. An alert built on that metric would look correct, pass review, and never fire once: a
# silent guard.
#
# `docker inspect` reads the same state cAdvisor fails to reach, and works fine in the guest, so
# this reads it directly and exports it under a DISTINCT metric name. It does not shadow or
# override the cAdvisor series — two metrics with the same name and different semantics would be
# its own trap.
#
# HEALTH IS TRISTATE, and conflating the third value is the easy mistake. Docker reports:
#   healthy / unhealthy / starting  — only for containers that DEFINE a healthcheck
#   (no health object at all)        — for containers that do not
# Most containers have no healthcheck. Exporting those as 0 would make "not
# monitored" indistinguishable from "healthy" and would quietly inflate any "everything is fine"
# panel. So containers WITHOUT a healthcheck get no health series at all — only the _info series.
#
# WRITES ATOMICALLY (.tmp + rename) for the same reason as intel-gpu-metrics.sh: node_exporter may
# scrape mid-write and would otherwise read a truncated file.
set -uo pipefail

OUT="${1:-/var/lib/node_exporter/textfile_collector/docker_health.prom}"
TMP="${OUT}.$$.tmp"

emit() { printf '%s\n' "$*" >> "$TMP"; }

: > "$TMP"

# ONE HELP LINE PER METRIC -- a second one makes node_exporter reject the whole file. See the
# same note in intel-gpu-metrics.sh.
emit "# HELP docker_container_health Healthcheck state: 1=healthy, 0=unhealthy, 2=starting. Emitted ONLY for containers defining a healthcheck -- absence means no healthcheck, NOT good health."
emit "# TYPE docker_container_health gauge"
emit "# HELP docker_container_health_failing_streak Consecutive failed healthchecks. 0 when healthy."
emit "# TYPE docker_container_health_failing_streak gauge"
emit "# HELP docker_container_running 1 if the container is running."
emit "# TYPE docker_container_running gauge"

# One `docker inspect` for every running container, rather than one call per container: this runs
# on a timer and forking one docker CLI per container per run is real load on a modest host.
# Tab-separated because container names cannot contain a tab, while other separators are riskier.
if ! ids=$(docker ps -q 2>/dev/null); then
  # Docker itself is unreachable. Emit the explicit signal rather than an empty file, so the
  # dashboard distinguishes "docker is down" from "this script never ran".
  emit "# HELP docker_health_exporter_up 1 if docker could be queried."
  emit "# TYPE docker_health_exporter_up gauge"
  emit "docker_health_exporter_up 0"
  chmod 0644 "$TMP" 2>/dev/null || true
  mv -f "$TMP" "$OUT"
  exit 0
fi

if [ -n "$ids" ]; then
  # shellcheck disable=SC2086
  docker inspect --format \
    '{{.Name}}	{{.State.Running}}	{{if .State.Health}}{{.State.Health.Status}}	{{.State.Health.FailingStreak}}{{else}}none	0{{end}}' \
    $ids 2>/dev/null | while IFS=$'\t' read -r name running status streak; do
      name="${name#/}"
      [ -n "$name" ] || continue

      case "$running" in true) r=1 ;; *) r=0 ;; esac
      emit "docker_container_running{name=\"${name}\"} ${r}"

      # A container with no healthcheck gets NO health series -- see the header.
      case "$status" in
        healthy)   emit "docker_container_health{name=\"${name}\"} 1" ;;
        unhealthy) emit "docker_container_health{name=\"${name}\"} 0" ;;
        starting)  emit "docker_container_health{name=\"${name}\"} 2" ;;
        *)         continue ;;
      esac
      emit "docker_container_health_failing_streak{name=\"${name}\"} ${streak:-0}"
    done
fi

emit "# HELP docker_health_exporter_up 1 if docker could be queried."
emit "# TYPE docker_health_exporter_up gauge"
emit "docker_health_exporter_up 1"

chmod 0644 "$TMP" 2>/dev/null || true
mv -f "$TMP" "$OUT"
