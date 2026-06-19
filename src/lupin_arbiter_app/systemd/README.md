# lupin-arbiter-app systemd --user unit (STAGED — held for Rick)

This unit is **staged, not installed or enabled**. Per the engagement gate, the
implementer does **not** actuate Rick's login session. Rick (or a Rick-authorized
operator) runs the steps below.

## Why `systemd --user` (not a system unit)

The dev box has no root for the :8001 service user — verified 2026-06-07:
`uid 1001`, `/etc/systemd/system` not writable, no passwordless `sudo`. So a
system unit is out. `systemd --user` keeps the unconditional `Restart=always`
guarantee (deploy doc §6 — the regress terminator) **without** root. Cron-only
was rejected: it loses that guarantee. `loginctl enable-linger` makes the user
manager survive logout so the watcher runs ~24/7 independent of an interactive
login.

Supervisor ladder actually selected (deploy doc R1): system-systemd ✗ (no root)
→ **user-systemd + linger ✓ (this unit)** → supervisord → cron.

## Install + enable (run by Rick)

```bash
# 0. (one time) confirm LUPIN_ROOT in the unit matches this host
#    grep Environment= lupin-arbiter-app.service

# 1. Copy the unit into the user systemd dir
mkdir -p ~/.config/systemd/user
cp "$LUPIN_ROOT/src/lupin_arbiter_app/systemd/lupin-arbiter-app.service" ~/.config/systemd/user/

# 2. Survive logout. On this box `loginctl enable-linger` for your own user MAY
#    need a one-time polkit/sudo grant — if the plain form is denied, use sudo.
loginctl enable-linger "$USER"            # if denied: sudo loginctl enable-linger "$USER"

# 3. Reload + enable + start
systemctl --user daemon-reload
systemctl --user enable --now lupin-arbiter-app.service

# 4. Verify liveness (ops health check — NOT a test surface)
systemctl --user status lupin-arbiter-app.service
curl -s http://127.0.0.1:8001/health      # expect {"status":"ok", ...}
```

## Bounce-survival check (the out-of-band guarantee)

With the unit active, restarting the dev container must NOT affect :8001:

```bash
docker restart lupin-rest-dev
curl -s http://127.0.0.1:8001/health      # still {"status":"ok"} — :8001 untouched
```

That independence is the whole point (deploy doc §2): a monitor must be
out-of-band from the monitored. :8001 survives every dev bounce and every
:8000 test-monopolization run.

## Belt-and-suspenders cron (optional, deploy doc §6)

systemd restarts a *crashed* process; a *hung-but-not-exited* process needs an
external liveness poke. Until `WatchdogSec` + `sd_notify` lands (V2), an optional
user crontab line covers the gap:

```cron
*/5 * * * * curl -fs http://127.0.0.1:8001/health >/dev/null || systemctl --user restart lupin-arbiter-app.service
```

## Uninstall / rollback (symmetric)

```bash
systemctl --user disable --now lupin-arbiter-app.service
rm ~/.config/systemd/user/lupin-arbiter-app.service
systemctl --user daemon-reload
# (optional) loginctl disable-linger "$USER"
```
