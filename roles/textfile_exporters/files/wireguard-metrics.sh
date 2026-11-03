#!/usr/bin/env bash
#
# Emits WireGuard tunnel state as Prometheus metrics, for node_exporter's textfile collector.
#
# WHY THIS EXISTS. A site link is invisible until it breaks. When a tunnel carries telemetry FROM a
# box that has no other monitoring, "is the tunnel up" cannot itself be answered by something that
# travels over the tunnel. These metrics are scraped on the monitored side, where the collector
# already lives.
#
# HANDSHAKE AGE IS THE SIGNAL, not an up/down flag. WireGuard is connectionless: an idle tunnel has
# no state to report, and `ip link` shows the interface UP whether or not the far end exists. The
# only honest liveness measure is how long ago the last handshake completed — WireGuard rekeys
# roughly every two minutes when traffic flows, so an age much beyond that means the far end is
# gone.
#
# RX IS EXPORTED SEPARATELY FROM TX, and that distinction matters. WireGuard silently DROPS a
# decrypted packet whose source address is outside that peer's AllowedIPs. A misconfigured
# AllowedIPs therefore produces a perfectly healthy handshake, a rising TX counter, and an RX
# counter pinned at zero — which looks like "the far end is quiet" and is actually "every packet we
# receive is being discarded". Alerting on handshake age alone would never catch it.
#
# FIELD LAYOUT of `wg show <if> dump` (tab-separated) — checked against a live tunnel, not from
# memory, because a wrong-index read of a fixed-column format silently reports the wrong field:
#
#   line 1, INTERFACE, 4 fields:
#     [1] private-key   [2] public-key   [3] listen-port   [4] fwmark
#   lines 2+, PEERS, 8 fields:
#     [1] public-key    [2] preshared-key [3] endpoint     [4] allowed-ips
#     [5] latest-handshake (UNIX epoch, 0 = never)
#     [6] transfer-rx (bytes)   [7] transfer-tx (bytes)   [8] persistent-keepalive
#
# NEVER parses `wg show` without `dump`: the human-readable output is fixed-width prose
# ("1 minute, 2 seconds ago") that invites fragile regex parsing.
#
# WRITES ATOMICALLY (.tmp + rename) — node_exporter may scrape mid-write.
#
# Usage: wireguard-metrics.sh <output.prom> [interface]

set -uo pipefail

OUT="${1:?usage: $0 <output.prom> [interface]}"
IFACE="${2:-wg0}"
TMP="${OUT}.tmp"
NOW="$(date +%s)"

# `wg show` needs root and the module loaded; both can legitimately be false on a host that is not
# a peer, so a failure here is a RESULT to export, not an error to die on.
DUMP=""
if command -v wg >/dev/null 2>&1; then
    DUMP="$(wg show "$IFACE" dump 2>/dev/null || true)"
fi

{
    echo "# HELP wireguard_up Whether the WireGuard interface exists and is readable (1) or not (0)."
    echo "# TYPE wireguard_up gauge"
    if [ -n "$DUMP" ]; then
        echo "wireguard_up{interface=\"${IFACE}\"} 1"
    else
        # Explicit 0 rather than an empty file: "the interface is gone" and "the exporter never
        # ran" must not look the same on a dashboard.
        echo "wireguard_up{interface=\"${IFACE}\"} 0"
    fi

    if [ -n "$DUMP" ]; then
        echo "# HELP wireguard_peers Number of configured peers on this interface."
        echo "# TYPE wireguard_peers gauge"
        printf '%s\n' "$DUMP" | awk -F'\t' -v iface="$IFACE" '
            NR > 1 { peers++ }
            END { printf "wireguard_peers{interface=\"%s\"} %d\n", iface, peers + 0 }'

        echo "# HELP wireguard_latest_handshake_seconds Seconds since this peer last completed a handshake. -1 means never."
        echo "# TYPE wireguard_latest_handshake_seconds gauge"
        # Peer lines only (NR > 1). Field [5] is the handshake epoch; 0 means it has never
        # completed one, which is NOT the same as "a long time ago" — exported as -1 so a
        # never-connected peer cannot be mistaken for a stale one.
        printf '%s\n' "$DUMP" | awk -F'\t' -v iface="$IFACE" -v now="$NOW" '
            NR > 1 {
                age = ($5 == 0) ? -1 : now - $5
                printf "wireguard_latest_handshake_seconds{interface=\"%s\",peer=\"%s\"} %d\n", iface, $1, age
            }'

        echo "# HELP wireguard_transfer_rx_bytes_total Bytes RECEIVED from this peer."
        echo "# TYPE wireguard_transfer_rx_bytes_total counter"
        printf '%s\n' "$DUMP" | awk -F'\t' -v iface="$IFACE" '
            NR > 1 { printf "wireguard_transfer_rx_bytes_total{interface=\"%s\",peer=\"%s\"} %d\n", iface, $1, $6 }'

        echo "# HELP wireguard_transfer_tx_bytes_total Bytes SENT to this peer."
        echo "# TYPE wireguard_transfer_tx_bytes_total counter"
        printf '%s\n' "$DUMP" | awk -F'\t' -v iface="$IFACE" '
            NR > 1 { printf "wireguard_transfer_tx_bytes_total{interface=\"%s\",peer=\"%s\"} %d\n", iface, $1, $7 }'
    fi
} > "$TMP"

mv -f "$TMP" "$OUT"
