# service_homepage

Deploy **gethomepage/homepage** (`ghcr.io/gethomepage/homepage`) as a
links-and-widgets overview dashboard: one page linking monitoring, network,
media and infrastructure services, as a Docker Compose service on a shared
network with a host port for a reverse proxy to front.

## What it does

- **Validates the dashboard config before deploying it** (`tasks/validate.yml`):
  renders `services`, `settings` and `bookmarks` on the controller and refuses
  to deploy when
  - a file does not parse to the shape homepage expects (the usual cause is a
    mis-indented `{% if %}` guard — every substring check would still pass);
  - a `services.yaml` section has no matching `settings.yaml` `layout:` entry
    (homepage renders it unstyled and out of order, which looks like a broken
    page rather than a config error) — checked only when a layout is declared;
  - a card has no `href`, or links a host matching
    `homepage_forbidden_href_patterns`;
  - a bookmark has no `href`/`icon`, or matches
    `homepage_bookmarks_forbidden_href_pattern`.
- Templates `docker-compose.yml` and the `config/*.yaml` files into
  `/opt/homepage` (via `richard_lynch.common.deployment_config`) and brings the
  container up on `homepage_network`, published on `homepage_host_port` (default
  `3010`).
- Restarts the stack when the rendered config changes (bind-mounted config edits
  don't recreate the container).
- **Read-back after deploy**: asserts the container is running and that
  `http://localhost:<homepage_host_port>/` answers 200. A just-restarted
  container resets its first connections, so the check retries
  (`homepage_health_retries`, default 12, `homepage_health_delay` seconds apart,
  default 5) and an assert after the loop fails the run if it never answers.

## Content is the caller's

The role's own config (`templates/config/`) is an **empty page**: which
services, bookmarks and layout a dashboard shows is installation data. Point
`homepage_config_src` at a controller directory holding your `services.yaml.j2`,
`settings.yaml.j2`, `bookmarks.yaml.j2`, `widgets.yaml.j2` and `docker.yaml.j2`
(plain `.yaml` works too); that directory **replaces** the default set as a
whole, so the role never writes a default file the caller's would then overwrite
on every run.

- **Services** are cards with a `siteMonitor` ping and, optionally, a widget.
- **Bookmarks** are plain links with no monitoring — right for third-party
  platforms, where a ping says whether a global CDN is up, not whether your
  service is.
- **Icons**: homepage resolves a bare `name.png` against the dashboard-icons
  set; a name that does not exist there renders as a broken image rather than an
  error, so check the exact slug.

### Widget credentials

`homepage_sonarr_api_key`, `homepage_radarr_api_key`,
`homepage_prowlarr_api_key`, `homepage_sabnzbd_api_key`,
`homepage_homeassistant_token` (and the Proxmox token pair) are passed to the
templates and are never logged. A caller's `services.yaml.j2` should render a
widget's `key:` field only when its value is non-empty, so an unset key means
"no widget credentials" rather than "widget configured with a blank key".

## Why no `docker.sock`

The compose file mounts **no** `/var/run/docker.sock` and no data path. An
overview page does not need host Docker access to be useful, and leaving it out
keeps the container's compromise blast radius small. `docker.yaml` ships as an
explanatory stub, and no `container:` field can be used in `services.yaml` as a
result.

## File modes

The rendered config carries the widget API keys, so it is written **0640
root:`homepage_pgid`**: not 0644 (world-readable keys), and not 0600 root:root
either — the container runs as `homepage_puid`/`homepage_pgid` and reads the
config through a bind mount, so a root-only file makes homepage start and render
an EMPTY dashboard while the HTTP gate still gets its 200.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml). Key ones:

- `homepage_config_src` (default empty: the role's empty page).
- `homepage_allowed_hosts` — `HOMEPAGE_ALLOWED_HOSTS`, every name the page is
  reached by; empty leaves homepage's own default (localhost only).
- `homepage_title`, `homepage_description`, `homepage_instance_name` — for
  `settings.yaml`.
- `homepage_forbidden_href_patterns`,
  `homepage_bookmarks_forbidden_href_pattern`.
- `homepage_image` (pinned, never `:latest`), `homepage_network`,
  `homepage_host_port`, `homepage_health_retries`/`homepage_health_delay`,
  `homepage_puid`/`homepage_pgid`/`homepage_umask`/`homepage_tz`.

## Usage

```yaml
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_homepage
      vars:
        homepage_config_src: "{{ playbook_dir }}/files/homepage-config"
        homepage_allowed_hosts: "home.example.test"
        homepage_title: "Example Home"
        homepage_bookmarks_forbidden_href_pattern: 'example\.test'
```

## Testing

`molecule/default/` renders the compose file (pinned image, network, port, no
`docker.sock`, the allowed-hosts variable present only when set) and runs the
role's real `validate.yml` in both directions: the default config and a good
fixture pass, and a section/layout mismatch, a forbidden card link and a
forbidden bookmark are each refused. A widget-guard check proves a set key
renders its widget and an empty one omits it. The post-deploy HTTP check runs
against a local endpoint that resets its first two connections (it must pass)
and against one that never answers 200 (it must fail through its gate).
