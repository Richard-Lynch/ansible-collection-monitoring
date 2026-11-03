#!/usr/bin/env bash
#
# Emits the site's PUBLIC EGRESS IP as a Prometheus metric, for node_exporter's textfile collector.
#
# WHY THIS EXISTS. A source-IP allow or bypass policy (an SSO bypass for a site's own network, a
# firewall allow-list) is pinned to one address: the WAN egress IP. "Static" from a residential ISP
# means "has not changed yet", not "cannot change".
#
# The failure mode if it DOES change is nasty precisely because it is not an outage: the policy
# stops matching and falls through to the next rule, and the symptom is an unexpected login prompt
# or a refused connection on something that worked yesterday. Nothing is down, no alert fires, and
# the cause (an ISP lease change days earlier) is invisible from the symptom. This exports the fact
# so a change is VISIBLE rather than inferred.
#
# WHAT IT EXPORTS, AND WHY IT IS SHAPED THIS WAY.
#   estate_wan_egress_ip_info{ip="a.b.c.d"} 1   -- the address, as a LABEL on an info-style series
#   estate_wan_egress_ip_lookup_success 1|0     -- did we actually learn it this run
#   estate_wan_egress_ip_matches_expected 1|0   -- does it equal the address the policy pins
#
# A Prometheus metric VALUE is a float and cannot hold an IPv4 address, so the address travels as a
# label on an info series (the standard _info convention). Alerting on the label CHANGING is then a
# `changes()` query over the series, which is exactly what "tell me when it moves" means.
#
# THREE SERIES, NOT ONE, because they answer different questions and conflating them creates a
# silent guard. If a lookup failure emitted "no match", a dead uplink and a changed IP would look
# identical, and the alert would fire for the wrong reason. If a failure emitted nothing at all, the
# expected-match series would go STALE holding its last value of 1 — reading as "still fine" for as
# long as Prometheus retains it. So: success is its own series, and on failure the match series is
# deliberately NOT emitted (absence is honest) while success goes to 0.
#
# THE EXPECTED ADDRESS IS PASSED IN, NOT BAKED IN. It is the policy's value, and the whole
# point is to notice when reality diverges from it — a hardcoded copy here would be a second source
# of truth to forget to update.
#
# WHY NOT JUST CURL IN A PLAY. Because a play runs when someone runs it. The question "has the WAN IP
# changed?" needs answering continuously and unattended; a timer + textfile collector is the
# pattern for exactly that (as for this role's other exporters).
#
# EXTERNAL DEPENDENCY, HANDLED. This necessarily reaches the public internet. Two independent
# resolvers are tried so one provider's outage does not read as a WAN IP change; if BOTH fail we
# report lookup_success 0 rather than guessing.
#
# WRITES ATOMICALLY (.tmp + rename) — node_exporter may scrape mid-write and would otherwise read a
# truncated file. Same contract as the other exporters in this role.
#
# Usage: wan-egress-ip-metrics.sh <output.prom> [expected_ip]

set -uo pipefail

OUT="${1:?usage: $0 <output.prom> [expected_ip]}"
EXPECTED="${2:-}"
TMP="${OUT}.tmp"

# --- discover the egress address -----------------------------------------------------------------
# Cloudflare's trace endpoint first, then ipify as an independent check.
#
# DOES NOT ASSUME curl. A minimal host often has only wget or python3, and a curl-only version would
# install cleanly, pass every gate, and then report lookup_success 0 forever: an exporter that is
# permanently blind looks identical to a genuine uplink failure. So each fetch tries curl, then
# wget, then python3, and only reports failure when all three are unavailable or all of them fail.
fetch() {
    # $1 = url. Prints the body on stdout, empty on failure.
    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 10 "$1" 2>/dev/null && return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO- --timeout=10 --tries=1 "$1" 2>/dev/null && return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import sys,urllib.request
try:
    sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=10).read().decode())
except Exception:
    pass" "$1" 2>/dev/null && return 0
    fi
    return 1
}

ip=""
if out=$(fetch https://cloudflare.com/cdn-cgi/trace); then
    ip=$(printf '%s\n' "$out" | sed -n 's/^ip=//p' | head -1)
fi
if [ -z "$ip" ]; then
    ip=$(fetch https://api.ipify.org || true)
fi

# Validate rather than trust: a captive portal or an error page would otherwise be exported as if it
# were an address, and the label would carry HTML into Prometheus.
if ! printf '%s' "$ip" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
    ip=""
fi

# --- emit ----------------------------------------------------------------------------------------
# Exactly ONE HELP and ONE TYPE line per metric name: a duplicate makes node_exporter reject the
# WHOLE FILE (node_textfile_scrape_error=1) while it sits on disk looking healthy. This role's own
# install gate checks for that.
{
    echo "# HELP estate_wan_egress_ip_lookup_success Whether the public egress IP could be determined this run (1) or not (0)."
    echo "# TYPE estate_wan_egress_ip_lookup_success gauge"
    if [ -n "$ip" ]; then
        echo "estate_wan_egress_ip_lookup_success 1"
    else
        echo "estate_wan_egress_ip_lookup_success 0"
    fi

    if [ -n "$ip" ]; then
        echo "# HELP estate_wan_egress_ip_info The site's public egress IPv4 address, carried as a label."
        echo "# TYPE estate_wan_egress_ip_info gauge"
        echo "estate_wan_egress_ip_info{ip=\"${ip}\"} 1"
    fi

    # Only meaningful when we BOTH know the current address and were told what to expect. Emitted
    # only then — see the header: a stale 1 here would read as "still matching" indefinitely.
    if [ -n "$ip" ] && [ -n "$EXPECTED" ]; then
        echo "# HELP estate_wan_egress_ip_matches_expected Whether the egress IP equals the expected (pinned) address."
        echo "# TYPE estate_wan_egress_ip_matches_expected gauge"
        if [ "$ip" = "$EXPECTED" ]; then
            echo "estate_wan_egress_ip_matches_expected 1"
        else
            echo "estate_wan_egress_ip_matches_expected 0"
        fi
    fi
} > "$TMP"

mv -f "$TMP" "$OUT"
