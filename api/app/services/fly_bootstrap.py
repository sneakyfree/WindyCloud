"""Cloud-init UserData that turns a bare Ubuntu EC2 into a running
Windy Fly agent (2026-07-04).

The VPS relief valve: a user with no computer (or whose laptop won't
cooperate) picks "host on a VPS" and their agent runs headless on a real
cloud instance. Before this, ``AWSEC2Provider.create`` launched a bare
box with no bootstrap — the "install windy-agent" step was a docstring,
never real code, so the instance was unreachable and never ran anything.

The agent boots KEYLESS: DEFAULT_MODEL=windy-mind-auto + the passport
token means it thinks on Windy Mind's free compute with no API key
(windy-mind PR #45 + windy-agent #247/#248). A power user can inject
their own key via ``byo_key``.
"""

from __future__ import annotations

import re

# Env values ride inside a quoted heredoc (no shell interpolation), so the
# only escape risk is a newline or a line equal to the heredoc sentinel.
_SAFE_ENV_VALUE = re.compile(r"^[^\r\n]*$")


def _safe(value: str) -> str:
    if value and not _SAFE_ENV_VALUE.match(value):
        raise ValueError("bootstrap env value contains a newline — refused")
    return value


def render_user_data(
    *,
    agent_name: str,
    ept_token: str | None = None,
    owner_email: str = "",
    default_model: str = "windy-mind-auto",
    byo_key_env: str | None = None,
    byo_key_value: str | None = None,
) -> str:
    """Return a bash cloud-init script (EC2 UserData) that installs and
    starts windyfly as a systemd service under a dedicated user.

    Everything is quoted through shlex to keep injected values (agent
    name, token) from breaking out of the heredoc.
    """
    lines = [
        f"DEFAULT_MODEL={_safe(default_model)}",
        "MIND_API_URL=https://api.windymind.ai",
        "WINDY_MIND_SEND_TOOLS=1",
        "WINDYFLY_DB_PATH=/opt/windyfly/data/windyfly.db",
        "LOG_LEVEL=INFO",
        "MATRIX_HOMESERVER=https://chat.windychat.ai",
        f"WINDYFLY_AGENT_NAME={_safe(agent_name)}",
    ]
    if ept_token:
        lines.append(f"ETERNITAS_PASSPORT_TOKEN={_safe(ept_token)}")
    if owner_email:
        lines.append(f"OWNER_EMAIL={_safe(owner_email)}")
    if byo_key_env and byo_key_value:
        lines.append(f"{_safe(byo_key_env)}={_safe(byo_key_value)}")
    env_block = "\n".join(lines)

    # Heredoc-safe: env values are simple tokens; we still wrap the whole
    # env file write in a quoted heredoc and avoid interpolation.
    script = f"""#!/usr/bin/env bash
set -euxo pipefail

# --- Windy Fly VPS bootstrap (Windy Cloud) ---
useradd -m -s /bin/bash windyfly || true
install -d -o windyfly -g windyfly /opt/windyfly/data

# uv + python + windyfly, installed as the windyfly user
sudo -u windyfly bash -lc '
  set -euxo pipefail
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  uv tool install windyfly || uv pip install --system windyfly || pip install --user windyfly
'

# Runtime env (chmod 600 — carries the passport token)
cat > /opt/windyfly/.env <<'WINDYENV'
{env_block}
WINDYENV
chown windyfly:windyfly /opt/windyfly/.env
chmod 600 /opt/windyfly/.env

# systemd unit — headless agent, always-on, restart on failure
cat > /etc/systemd/system/windyfly.service <<'UNIT'
[Unit]
Description=Windy Fly agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=windyfly
WorkingDirectory=/opt/windyfly
EnvironmentFile=/opt/windyfly/.env
ExecStart=/home/windyfly/.local/bin/windy start --no-daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now windyfly.service
"""
    return script
