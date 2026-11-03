# apprise_notify_config

Push notification targets — **Home Assistant, email, Slack** — into an Apprise stateful **config-id**
(the target Alertmanager POSTs to at `/notify/<config-id>`). Apprise fans each alert out to every
enabled target.

## What it does

- Renders an Apprise YAML config from the enabled targets and `POST`s it to
  `{{ apprise_notify_base_url }}/add/{{ apprise_notify_config_id }}`.
- **Each target is independent**: a target whose credential (or HA host) is empty is **skipped** —
  so HA and email can be wired now and Slack added later without breaking anything.
- The rendered config and the request carrying it are `no_log`: they hold every target's
  credential.

## Targets

| Target | Apprise URL | Inputs |
|---|---|---|
| Home Assistant | `hassio://{host}:{port}/{token}` | `apprise_notify_ha_host`, `apprise_notify_ha_token` (a long-lived access token) |
| Email | `mailto://{user}:{app-pw}@gmail.com?to={dest}` | Gmail sender, app password and destination |
| Slack | `slack://…` (from an Incoming Webhook) | `apprise_notify_slack_url` |

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml). Every credential and the HA host are
installation config with an empty default; the caller resolves them (from its secret store) and
passes them in.

## Usage

```yaml
- hosts: monitoring
  gather_facts: false
  roles:
    - role: richard_lynch.monitoring.apprise_notify_config
      vars:
        apprise_notify_ha_host: "192.0.2.10"
        apprise_notify_ha_token: "{{ ha_token }}"
        apprise_notify_email_user: "sender@example.com"
        apprise_notify_email_password: "{{ gmail_app_password }}"
        apprise_notify_email_to: "alerts@example.com"
```

Test a target: `curl -XPOST http://<apprise-host>:8000/notify/alerts -d 'body=test&title=hello'`.

## Testing

`molecule/default/` renders the config template with sample creds and asserts each enabled target's
URL scheme appears, and that a target with no credential is omitted (offline).
