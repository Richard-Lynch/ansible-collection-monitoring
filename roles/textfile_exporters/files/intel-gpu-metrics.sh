#!/usr/bin/env bash
#
# Emits Prometheus metrics for Intel GPUs from sysfs, for node_exporter's textfile collector.
#
# WHY SYSFS AND NOT intel_gpu_top. A packaged `intel_gpu_top` that predates the `xe` driver can
# SEGFAULT on a Battlemage card. Even where it works it must run continuously to sample and holds
# the device open. sysfs is stable, free to read and needs no daemon.
#
# WHAT SERVES AS "BUSY". sysfs on xe exposes no per-engine utilisation percentage. The usable
# proxy, confirmed by sampling during a transcode, is `act_freq` — the GT's ACTUAL clock:
#
#     idle:              act_freq = 0
#     during transcode:  act_freq = 400   (on gt1, the video GT)
#
# So act_freq > 0 means that GT is doing work. Note `cur_freq` is NOT a busy signal — it reads a
# constant 1200 whether idle or loaded, because it reports the requested floor rather than the
# achieved clock. Graphing cur_freq would show a permanently busy GPU.
#
# `idle_residency_ms` is a COUNTER that keeps rising even under load, so it is not an
# inverse-utilisation signal either; it is exported for completeness, not as a load metric.
#
# WRITES ATOMICALLY. node_exporter reads whatever is in the .prom file whenever it scrapes; writing
# in place would let it read a half-written file and emit garbage or drop series. Write to .tmp and
# rename — rename is atomic on the same filesystem.
#
# Fails SOFT: a missing sysfs entry is skipped rather than aborting, so one unreadable value never
# costs the whole scrape. But a GPU that disappears entirely produces NO series at all, which is
# itself the signal — a gap in the graph rather than a silent zero.
set -uo pipefail

OUT="${1:-/var/lib/node_exporter/textfile_collector/intel_gpu.prom}"
TMP="${OUT}.$$.tmp"

# Where to look for cards. Overridable ONLY so the molecule scenario can point the real script at a
# fixture tree -- otherwise this script would be testable only on a host that physically has the
# GPU, which is precisely the code that most needs a test. Production never sets it.
DRM_ROOT="${DRM_ROOT:-/sys/class/drm}"

emit() { printf '%s\n' "$*" >> "$TMP"; }

# Read a sysfs file, print nothing if unreadable/empty. Never returns an error.
rd() { if [ -r "$1" ]; then cat "$1" 2>/dev/null || true; fi; }

: > "$TMP"

# EXACTLY ONE HELP LINE PER METRIC. The Prometheus text format permits a single HELP per metric
# name; a second one is a hard parse error ("second HELP line for metric name ...") that makes
# node_exporter reject the ENTIRE FILE, not just that metric: the file is present and full of valid
# samples, and node_textfile_scrape_error simply goes to 1. Keep each HELP on one line however
# long, and put the long-form explanation in this header instead.
emit "# HELP intel_gpu_info Static labels describing each Intel GPU present."
emit "# TYPE intel_gpu_info gauge"
emit "# HELP intel_gpu_freq_mhz GPU clock in MHz. kind=act is the ACHIEVED clock and is the usable busy signal (0 when idle); kind=cur is the requested floor and does NOT indicate load."
emit "# TYPE intel_gpu_freq_mhz gauge"
emit "# HELP intel_gpu_idle_residency_ms Cumulative GT idle time. Keeps rising under load too -- NOT an inverse-utilisation metric. Use freq kind=act."
emit "# TYPE intel_gpu_idle_residency_ms counter"
emit "# HELP intel_gpu_fan_rpm Fan speed in RPM. 0 is normal on a passive/idle card."
emit "# TYPE intel_gpu_fan_rpm gauge"
emit "# HELP intel_gpu_power_limit_watts Configured power limit."
emit "# TYPE intel_gpu_power_limit_watts gauge"
emit "# HELP intel_gpu_temp_celsius GPU temperature, where the driver exposes one."
emit "# TYPE intel_gpu_temp_celsius gauge"
emit "# HELP intel_gpu_vram_bytes VRAM totals as the driver reports them."
emit "# TYPE intel_gpu_vram_bytes gauge"

for dev in "$DRM_ROOT"/card*/device; do
  [ -d "$dev" ] || continue
  # Only PCI display devices — skip render-only symlinks and anything without a PCI address.
  addr=$(basename "$(readlink -f "$dev")" 2>/dev/null)
  case "$addr" in *:*:*.*) ;; *) continue ;; esac

  drv=$(basename "$(readlink -f "$dev/driver" 2>/dev/null)" 2>/dev/null)
  [ -n "$drv" ] || drv="none"
  vendor=$(rd "$dev/vendor"); device=$(rd "$dev/device")
  LBL="pci=\"${addr}\",driver=\"${drv}\",device_id=\"${vendor#0x}:${device#0x}\""

  emit "intel_gpu_info{${LBL}} 1"

  # --- frequency, per GT ---------------------------------------------------------------------
  # A discrete Arc has MULTIPLE GTs and the video engines live on gt1, not gt0 — reporting only
  # gt0 would show an idle-looking card during a transcode. Every GT is emitted, labelled.
  for gt in "$dev"/tile*/gt*; do
    [ -d "$gt" ] || continue
    gtname=$(basename "$gt")
    tile=$(basename "$(dirname "$gt")")
    GL="${LBL},gt=\"${tile}/${gtname}\""

    for kind in act cur max min; do
      v=$(rd "$gt/freq0/${kind}_freq")
      [ -n "$v" ] && emit "intel_gpu_freq_mhz{${GL},kind=\"${kind}\"} ${v}"
    done

    v=$(rd "$gt/gtidle/idle_residency_ms")
    [ -n "$v" ] && emit "intel_gpu_idle_residency_ms{${GL}} ${v}"

    # Which engines this GT has, so a dashboard can tell the render GT from the video GT without
    # hardcoding the topology.
    if [ -d "$gt/engines" ]; then
      for e in "$gt"/engines/*; do
        [ -d "$e" ] || continue
        emit "intel_gpu_engine_info{${GL},engine=\"$(basename "$e")\"} 1"
      done
    fi
  done

  # --- hwmon: fans, power, temperature -------------------------------------------------------
  for hw in "$dev"/hwmon/hwmon*; do
    [ -d "$hw" ] || continue
    for f in "$hw"/fan*_input; do
      [ -r "$f" ] || continue
      n=$(basename "$f"); n=${n%_input}
      emit "intel_gpu_fan_rpm{${LBL},fan=\"${n}\"} $(rd "$f")"
    done
    # microwatts -> watts; microdegrees -> degrees. Emitting raw sysfs units would make a
    # dashboard show 320000000 "watts", which is the sort of thing nobody notices until it is
    # embarrassing.
    for f in "$hw"/power*_crit "$hw"/power*_max; do
      [ -r "$f" ] || continue
      v=$(rd "$f"); [ -n "$v" ] || continue
      n=$(basename "$f")
      emit "intel_gpu_power_limit_watts{${LBL},limit=\"${n}\"} $(awk -v x="$v" 'BEGIN{printf "%.2f", x/1000000}')"
    done
    for f in "$hw"/temp*_input; do
      [ -r "$f" ] || continue
      v=$(rd "$f"); [ -n "$v" ] || continue
      n=$(basename "$f"); n=${n%_input}
      emit "intel_gpu_temp_celsius{${LBL},sensor=\"${n}\"} $(awk -v x="$v" 'BEGIN{printf "%.1f", x/1000}')"
    done
  done

  # --- VRAM ------------------------------------------------------------------------------------
  # On a small-BAR card, total and CPU-visible differ enormously (gigabytes vs 256MB), and that
  # distinction decides what the card can do — worth graphing rather than hiding.
  for m in mem_info_vram_total mem_info_vram_used; do
    v=$(rd "$dev/$m")
    [ -n "$v" ] && emit "intel_gpu_vram_bytes{${LBL},kind=\"${m#mem_info_vram_}\"} ${v}"
  done
done

# A file with only HELP/TYPE lines and no samples means every GPU vanished. Emit an explicit zero
# so the absence is visible as a value rather than as a missing series that could be mistaken for
# a scrape problem.
if ! grep -q '^intel_gpu_info{' "$TMP" 2>/dev/null; then
  emit "# HELP intel_gpu_present Number of Intel GPUs found. 0 means none were detected."
  emit "# TYPE intel_gpu_present gauge"
  emit "intel_gpu_present 0"
fi

chmod 0644 "$TMP" 2>/dev/null || true
mv -f "$TMP" "$OUT"
