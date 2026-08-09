# VCA Reservation Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Linux systemd-timer monitor that checks six Japanese VCA boutiques hourly and sends a SeaTalk message every successful run, mentioning all members only when jewelry availability changed.

**Architecture:** A dependency-free Python package reads the public Richemont Canvas APIs, normalizes the response into an immutable deterministic snapshot, compares it with atomically persisted state, and sends SeaTalk incoming-webhook text messages. A one-shot systemd service runs through an hourly persistent timer; the package exposes separate production, read-only smoke, and webhook-test commands.

**Tech Stack:** Python 3.11+, standard-library `urllib`, `dataclasses`, and `zoneinfo`; pytest and Ruff for development; systemd for Linux scheduling.

## Global Constraints

- Monitor exactly the six boutiques listed in the approved design.
- Count only `RICBA_Sales` jewelry-viewing slots; never count after-sales service slots.
- Send one SeaTalk message after every successful hourly check.
- Set SeaTalk `text.at_all=true` whenever a successful snapshot differs from the last successful snapshot, including a changed recovery run.
- Never commit, log, or include the SeaTalk webhook URL or callback signing secret in exceptions.
- Use Python 3.11+ and no third-party runtime dependencies.
- Persist mutable state at `/var/lib/vca-reservation/state.json` by default.
- Do not book appointments or submit personal information.

---

## File Structure

- `pyproject.toml`: package metadata, console entrypoint, pytest, and Ruff settings.
- `.gitignore`: local environments, caches, state, logs, and secret env files.
- `src/vca_reservation/boutiques.py`: immutable six-boutique configuration.
- `src/vca_reservation/models.py`: normalized snapshot and event value objects.
- `src/vca_reservation/client.py`: VCA HTTP calls and response validation.
- `src/vca_reservation/state.py`: atomic state serialization and snapshot diffing.
- `src/vca_reservation/seatalk.py`: message formatting and SeaTalk webhook transport.
- `src/vca_reservation/monitor.py`: success/failure state machine and orchestration.
- `src/vca_reservation/config.py`: environment parsing without secret disclosure.
- `src/vca_reservation/cli.py`: `run`, `smoke`, and `test-webhook` commands.
- `tests/`: unit and command tests with no network access.
- `deploy/`: example environment and systemd units.
- `scripts/install.sh`: idempotent root installation and timer activation.
- `scripts/uninstall.sh`: safe removal with optional state/config purge.
- `README.md`: Linux setup, operation, verification, logs, and recovery.

---

### Task 1: Package Foundation and VCA Client

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/vca_reservation/__init__.py`
- Create: `src/vca_reservation/boutiques.py`
- Create: `src/vca_reservation/models.py`
- Create: `src/vca_reservation/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces: `Boutique`, `DateAvailability`, `BoutiqueAvailability`, and `Snapshot` in `models.py`.
- Produces: `BOUTIQUES: tuple[Boutique, ...]` in `boutiques.py`.
- Produces: `VcaClient.fetch_snapshot(boutiques: tuple[Boutique, ...]) -> Snapshot`.
- `VcaClient` accepts an injectable `open_request: Callable[[Request, float], bytes]` for real-code tests without network mocks at the model boundary.

- [ ] **Step 1: Bootstrap package and development tooling**

Create an empty `src/vca_reservation/__init__.py`, a `.gitignore` covering `.venv/`,
`__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `state.json`, `*.log`, and
`.env`, plus this initial package configuration:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "vca-reservation"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["build>=1.2", "pytest>=8.0", "ruff>=0.6"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

Create the development environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

- [ ] **Step 2: Write the failing client tests**

Create fixtures inline in `tests/test_client.py`. The availability response must contain one date with `salesSlotsCount=2`, one service-only date, and one zero date. The time response for the sales date must contain one available slot plus blocked, web-blocked, and full slots.

```python
def test_fetch_snapshot_keeps_only_open_sales_slots():
    transport = FixtureTransport(
        availability=[
            {"recordDate": "2026-08-18", "salesSlotsCount": 2, "serviceSlotsCount": 5},
            {"recordDate": "2026-08-19", "salesSlotsCount": 0, "serviceSlotsCount": 4},
        ],
        times={
            "2026-08-18": [
                slot("14:00:00.000Z", capacity=1, assigned=0),
                slot("15:00:00.000Z", capacity=1, assigned=0, blocked=True),
                slot("16:00:00.000Z", capacity=1, assigned=0, blocked_for_web=True),
                slot("17:00:00.000Z", capacity=1, assigned=1),
            ]
        },
    )

    snapshot = VcaClient(open_request=transport).fetch_snapshot((TEST_BOUTIQUE,))

    assert snapshot[0].dates == (
        DateAvailability(date="2026-08-18", times=("14:00",)),
    )
    assert transport.requested_slot_types == ["RICBA_Sales"]


def test_fetch_snapshot_rejects_malformed_availability():
    client = VcaClient(open_request=lambda request, timeout: b'{"unexpected": true}')

    with pytest.raises(VcaResponseError, match="availability response must be a list"):
        client.fetch_snapshot((TEST_BOUTIQUE,))


def test_fetch_snapshot_is_deterministically_sorted():
    snapshot = VcaClient(open_request=UNSORTED_TRANSPORT).fetch_snapshot((BOUTIQUE_B, BOUTIQUE_A))

    assert [item.boutique_id for item in snapshot] == [BOUTIQUE_B.id, BOUTIQUE_A.id]
    assert snapshot[0].dates[0].times == ("13:00", "17:00")
```

- [ ] **Step 3: Run the tests and verify RED**

Run: `python3 -m pytest tests/test_client.py -q`

Expected: collection fails because `vca_reservation.client` does not exist.

- [ ] **Step 4: Implement the immutable models and exact boutique list**

Use frozen dataclasses and tuples so snapshot equality is structural and deterministic.

```python
@dataclass(frozen=True)
class Boutique:
    id: str
    external_id: str
    city: str
    name: str


@dataclass(frozen=True)
class DateAvailability:
    date: str
    times: tuple[str, ...]


@dataclass(frozen=True)
class BoutiqueAvailability:
    boutique_id: str
    city: str
    name: str
    dates: tuple[DateAvailability, ...]


Snapshot = tuple[BoutiqueAvailability, ...]
```

Populate `BOUTIQUES` with the six IDs recorded in the design research:

```python
BOUTIQUES = (
    Boutique("0011i00000S5lfnAAB", "GEMINI_8410", "大阪", "阪急梅田本店"),
    Boutique("0011i00000S5lfwAAB", "GEMINI_8421", "大阪", "大阪髙島屋店"),
    Boutique("0011i00000S5lekAAB", "GEMINI_8424", "大阪", "心斎橋店"),
    Boutique("0011i00000S5lfsAAB", "GEMINI_8416", "神户", "大丸神户店"),
    Boutique("0011i00001VAH6cAAH", "GEMINI_8425", "神户", "神户阪急店"),
    Boutique("001W600001FAK4xIAH", "GEMINI_8431", "广岛", "福屋八丁堀本店"),
)
```

- [ ] **Step 5: Implement the minimal validated API client**

Build query strings with `urllib.parse.urlencode`. Availability calls use `apiMethod=getBoutiqueAvailabilities`, and slot calls use `apiMethod=getTimeSlotsByDateAndType`, `type=RICBA_Sales`, and `useBoutiqueDuration=true`. Retain a slot only when:

```python
assigned = require_non_negative_int(item, "currentlyAssignedAppointmentsNumber")
capacity = require_non_negative_int(item, "appointmentsNumber")
is_open = assigned < capacity and not item.get("isBlocked") and not item.get("isBlockedForWeb")
```

The default transport reads at most the configured timeout and converts `URLError`, timeout, non-2xx, invalid JSON, and schema errors to `VcaRequestError` or `VcaResponseError` without including request URLs in messages.

- [ ] **Step 6: Run focused and static checks**

Run:

```bash
python3 -m pytest tests/test_client.py -q
python3 -m ruff check src/vca_reservation tests/test_client.py
```

Expected: all client tests pass and Ruff reports no errors.

- [ ] **Step 7: Commit Task 1**

```bash
git add pyproject.toml .gitignore src/vca_reservation tests/test_client.py
git commit -m "feat: read VCA jewelry availability"
```

---

### Task 2: Atomic State and Change Decisions

**Files:**
- Create: `src/vca_reservation/state.py`
- Create: `src/vca_reservation/monitor.py`
- Test: `tests/test_state.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `Snapshot` from Task 1.
- Produces: `MonitorState`, `StateStore.load()`, and `StateStore.save(state)`.
- Produces: `Event`, `decide_success(state, snapshot, checked_at)`, and `record_failure(state) -> MonitorState`.
- Produces: `run_monitor(client, notifier, store, now) -> Event`.

- [ ] **Step 1: Write failing serialization and atomicity tests**

```python
def test_state_round_trip_preserves_snapshot(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = MonitorState(last_snapshot=SAMPLE_SNAPSHOT, consecutive_failures=2, failure_alerted=True)

    store.save(state)

    assert store.load() == state


def test_failed_replace_leaves_previous_state_readable(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    store.save(MonitorState(last_snapshot=OLD_SNAPSHOT))
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk error")))

    with pytest.raises(StateWriteError, match="could not persist monitor state"):
        store.save(MonitorState(last_snapshot=NEW_SNAPSHOT))

    assert store.load().last_snapshot == OLD_SNAPSHOT
```

- [ ] **Step 2: Run state tests and verify RED**

Run: `python3 -m pytest tests/test_state.py -q`

Expected: import failure because `vca_reservation.state` does not exist.

- [ ] **Step 3: Implement state JSON and atomic replacement**

Serialize only plain JSON fields. Write a sibling temporary file with mode `0600`, flush and `os.fsync`, then call `os.replace`. Missing files load as a fresh state; malformed state raises `StateReadError` and is never silently discarded.

- [ ] **Step 4: Write failing event-decision tests**

```python
@pytest.mark.parametrize(
    ("state", "snapshot", "kind", "mention_all"),
    [
        (MonitorState(), EMPTY_SNAPSHOT, "initial", False),
        (MonitorState(last_snapshot=EMPTY_SNAPSHOT), EMPTY_SNAPSHOT, "heartbeat", False),
        (MonitorState(last_snapshot=EMPTY_SNAPSHOT), OPEN_SNAPSHOT, "changed", True),
        (
            MonitorState(last_snapshot=OPEN_SNAPSHOT, failure_alerted=True),
            OPEN_SNAPSHOT,
            "recovery",
            False,
        ),
        (
            MonitorState(last_snapshot=EMPTY_SNAPSHOT, failure_alerted=True),
            OPEN_SNAPSHOT,
            "recovery_changed",
            True,
        ),
    ],
)
def test_decide_success(state, snapshot, kind, mention_all):
    event, next_state = decide_success(state, snapshot, CHECKED_AT)

    assert event.kind == kind
    assert event.mention_all is mention_all
    assert next_state == MonitorState(last_snapshot=snapshot)


def test_third_failure_becomes_alertable_once():
    third = record_failure(MonitorState(consecutive_failures=2))
    fourth = record_failure(replace(third, failure_alerted=True))

    assert third.consecutive_failures == 3
    assert third.failure_alerted is False
    assert fourth.consecutive_failures == 4
    assert fourth.failure_alerted is True
```

- [ ] **Step 5: Run decision tests and verify RED**

Run: `python3 -m pytest tests/test_monitor.py -q`

Expected: import failure for missing monitor decision functions.

- [ ] **Step 6: Implement diffing, decisions, and orchestration**

Flatten snapshots to `(boutique_id, date, time)` tuples for set differences. `run_monitor` must always send one event on success, save a new successful state only after delivery, and preserve the last successful snapshot on VCA failure. Failure handling increments and saves the failure count; on counts 3 and above it retries the one failure alert until delivery succeeds, then saves `failure_alerted=True`.

- [ ] **Step 7: Run Task 2 checks**

```bash
python3 -m pytest tests/test_state.py tests/test_monitor.py -q
python3 -m ruff check src/vca_reservation/state.py src/vca_reservation/monitor.py tests/test_state.py tests/test_monitor.py
```

Expected: all Task 2 tests pass and Ruff reports no errors.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/vca_reservation/state.py src/vca_reservation/monitor.py tests/test_state.py tests/test_monitor.py
git commit -m "feat: track reservation changes atomically"
```

---

### Task 3: SeaTalk Formatting and Delivery

**Files:**
- Create: `src/vca_reservation/seatalk.py`
- Test: `tests/test_seatalk.py`
- Modify: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `Event` and `Snapshot` from Tasks 1 and 2.
- Produces: `format_event(event) -> str`, `format_failure(count, checked_at) -> str`, and `SeaTalkNotifier.send(content: str, mention_all: bool) -> None`.

- [ ] **Step 1: Write failing formatter tests**

```python
def test_changed_message_lists_diff_and_current_snapshot():
    content = format_event(CHANGED_EVENT)

    assert "VCA 预约号源有变化" in content
    assert "+ 广岛 福屋八丁堀本店 2026-08-18 14:00" in content
    assert "当前可预约" in content
    assert "日本时间" in content
    assert APPOINTMENT_URL in content


def test_heartbeat_explicitly_says_no_change():
    assert "本小时无变化" in format_event(HEARTBEAT_EVENT)


def test_message_is_below_seatalk_utf8_limit():
    content = format_event(OVERSIZED_EVENT)

    assert len(content.encode("utf-8")) <= 4000
    assert "内容已截断" in content
```

- [ ] **Step 2: Run formatter tests and verify RED**

Run: `python3 -m pytest tests/test_seatalk.py -q`

Expected: import failure because `vca_reservation.seatalk` does not exist.

- [ ] **Step 3: Implement deterministic Chinese message formatting**

Use headers `初始状态`, `本小时无变化`, `预约号源有变化`, `监控恢复`, and `监控恢复且号源有变化`. List additions with `+`, removals with `-`, then list every current open date and time. Empty snapshots render `当前六家门店均无珠宝预约号源`.

- [ ] **Step 4: Write failing SeaTalk transport tests**

```python
def test_changed_delivery_sets_at_all_true():
    recorder = RecordingOpener(response=b'{"code": 0}')
    notifier = SeaTalkNotifier("https://example.invalid/secret", open_request=recorder)

    notifier.send("changed", mention_all=True)

    assert recorder.json_body == {
        "tag": "text",
        "text": {"content": "changed", "at_all": True},
    }


def test_delivery_error_does_not_disclose_webhook():
    notifier = SeaTalkNotifier(SECRET_URL, open_request=FailingOpener())

    with pytest.raises(SeaTalkDeliveryError) as error:
        notifier.send("message", mention_all=False)

    assert SECRET_URL not in str(error.value)
```

- [ ] **Step 5: Implement webhook POST and redacted failures**

Send exactly:

```python
payload = {
    "tag": "text",
    "text": {"content": content, "at_all": mention_all},
}
```

Accept only HTTP 2xx. Catch transport and response failures and raise the fixed message `SeaTalk webhook delivery failed`; never interpolate the URL or response request object.

- [ ] **Step 6: Connect the notifier to monitor tests**

Add assertions that every successful event calls `send` exactly once, unchanged uses `mention_all=False`, and changed or recovery-changed uses `mention_all=True`. Assert state is not advanced when `send` raises.

- [ ] **Step 7: Run Task 3 checks**

```bash
python3 -m pytest tests/test_seatalk.py tests/test_monitor.py -q
python3 -m ruff check src/vca_reservation/seatalk.py tests/test_seatalk.py tests/test_monitor.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/vca_reservation/seatalk.py tests/test_seatalk.py tests/test_monitor.py
git commit -m "feat: notify SeaTalk on every check"
```

---

### Task 4: Configuration and CLI Commands

**Files:**
- Create: `src/vca_reservation/config.py`
- Create: `src/vca_reservation/cli.py`
- Test: `tests/test_config.py`
- Test: `tests/test_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `Config.from_env(require_webhook: bool) -> Config`.
- Produces console command: `vca-reservation {run,smoke,test-webhook}`.
- `run` performs production stateful monitoring.
- `smoke` performs a real VCA read, prints the normalized snapshot, and never sends SeaTalk.
- `test-webhook` sends one non-mentioning connection-test message and does not read VCA.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_run_requires_seatalk_webhook(monkeypatch):
    monkeypatch.delenv("SEATALK_WEBHOOK_URL", raising=False)

    with pytest.raises(ConfigError, match="SEATALK_WEBHOOK_URL is required"):
        Config.from_env(require_webhook=True)


def test_config_rejects_non_positive_timeout(monkeypatch):
    monkeypatch.setenv("VCA_HTTP_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigError, match="must be a positive number"):
        Config.from_env(require_webhook=False)
```

- [ ] **Step 2: Run configuration tests and verify RED**

Run: `python3 -m pytest tests/test_config.py -q`

Expected: import failure for missing configuration module.

- [ ] **Step 3: Implement environment parsing**

Default state path to `/var/lib/vca-reservation/state.json` and timeout to `15.0`. Validate that a required webhook begins with `https://openapi.seatalk.io/webhook/group/`, but never include its value in errors or dataclass `repr`.

- [ ] **Step 4: Write failing command tests**

```python
def test_smoke_never_constructs_notifier(monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_client", lambda config: StubClient(OPEN_SNAPSHOT))
    monkeypatch.setattr(cli, "build_notifier", Mock(side_effect=AssertionError("must not run")))

    assert cli.main(["smoke"]) == 0
    assert "福屋八丁堀本店" in capsys.readouterr().out


def test_test_webhook_never_queries_vca(monkeypatch):
    notifier = Mock()
    monkeypatch.setattr(cli, "build_notifier", lambda config: notifier)
    monkeypatch.setattr(cli, "build_client", Mock(side_effect=AssertionError("must not run")))

    assert cli.main(["test-webhook"]) == 0
    notifier.send.assert_called_once_with(ANY, mention_all=False)
```

- [ ] **Step 5: Run command tests and verify RED**

Run: `python3 -m pytest tests/test_cli.py -q`

Expected: import failure because `vca_reservation.cli` does not exist.

- [ ] **Step 6: Implement CLI and entrypoint**

Use `argparse` subcommands. Convert known domain errors to concise stderr plus exit code 1. Unexpected exceptions must still avoid printing the config object. Register:

```toml
[project.scripts]
vca-reservation = "vca_reservation.cli:entrypoint"
```

- [ ] **Step 7: Run Task 4 checks**

```bash
python3 -m pytest tests/test_config.py tests/test_cli.py -q
python3 -m ruff check src/vca_reservation/config.py src/vca_reservation/cli.py tests/test_config.py tests/test_cli.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 8: Commit Task 4**

```bash
git add pyproject.toml src/vca_reservation/config.py src/vca_reservation/cli.py tests/test_config.py tests/test_cli.py
git commit -m "feat: add monitor command interface"
```

---

### Task 5: Linux systemd Deployment and Operator Documentation

**Files:**
- Create: `deploy/vca-reservation.env.example`
- Create: `deploy/vca-reservation.service`
- Create: `deploy/vca-reservation.timer`
- Create: `scripts/install.sh`
- Create: `scripts/uninstall.sh`
- Create: `README.md`
- Test: `tests/test_deploy_files.py`

**Interfaces:**
- Consumes installed console command from Task 4.
- Produces hourly persistent systemd service under user `vca-reservation`.
- Produces idempotent installation that reads the secret only from `/etc/vca-reservation.env`.

- [ ] **Step 1: Write failing deployment-file tests**

```python
def test_timer_is_hourly_and_persistent():
    timer = Path("deploy/vca-reservation.timer").read_text()
    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer


def test_service_uses_dedicated_user_and_state_directory():
    service = Path("deploy/vca-reservation.service").read_text()
    assert "User=vca-reservation" in service
    assert "StateDirectory=vca-reservation" in service
    assert "EnvironmentFile=/etc/vca-reservation.env" in service


def test_repository_contains_no_real_webhook_or_callback_secret():
    credential_pattern = re.compile(
        r"https://openapi\.seatalk\.io/webhook/group/[A-Za-z0-9_-]{10,}"
    )
    for path in runtime_repository_files():
        assert credential_pattern.search(path.read_text(errors="ignore")) is None
```

- [ ] **Step 2: Run deployment tests and verify RED**

Run: `python3 -m pytest tests/test_deploy_files.py -q`

Expected: assertions fail because deployment files do not exist.

- [ ] **Step 3: Implement systemd units**

The service is `Type=oneshot`, uses `/opt/vca-reservation/.venv/bin/vca-reservation run`, sets `StateDirectory=vca-reservation`, and enables `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, and `ProtectHome=true`. The timer contains:

```ini
[Timer]
OnCalendar=hourly
Persistent=true
Unit=vca-reservation.service
```

- [ ] **Step 4: Implement safe installation scripts**

`install.sh` must require root, validate `/etc/vca-reservation.env` exists and contains a non-empty SeaTalk group webhook without printing it, create the system user if absent, create `/opt/vca-reservation/.venv`, install the local repository with `pip --no-deps`, install units, run `systemctl daemon-reload`, and enable/start the timer.

`uninstall.sh` stops and disables the timer, removes units and `/opt/vca-reservation`, then reloads systemd. Preserve `/etc/vca-reservation.env` and `/var/lib/vca-reservation` unless the operator explicitly passes `--purge`.

- [ ] **Step 5: Write operator README**

Document exact commands to clone, create the `0600` environment file, install, trigger a manual check, inspect timer status and journal logs, run `smoke` and `test-webhook`, update, and uninstall. Warn that the webhook URL is a secret and that the event-callback signing secret is not used.

- [ ] **Step 6: Run deployment and full repository checks**

```bash
python3 -m pytest -q
python3 -m ruff check .
python3 -m build
git grep -nE 'openapi\.seatalk\.io/webhook/group/[A-Za-z0-9_-]{10,}' -- . ':!docs/*'
```

Expected: tests, Ruff, and build pass. `git grep` returns exit code 1 with no matches.

- [ ] **Step 7: Commit Task 5**

```bash
git add deploy scripts README.md tests/test_deploy_files.py
git commit -m "feat: install hourly Linux monitor"
```

---

### Task 6: Live End-to-End Verification

**Files:**
- Modify only if verification exposes a defect.

**Interfaces:**
- Consumes the completed CLI and the user-provided SeaTalk webhook through an ephemeral environment variable.
- Produces live evidence without writing the webhook URL to disk.

- [ ] **Step 1: Run the read-only live VCA smoke check**

Run: `vca-reservation smoke`

Expected: six boutiques are present; availability corresponds to the official live endpoint; the command sends no SeaTalk message.

- [ ] **Step 2: Run the implemented SeaTalk test command**

Export `SEATALK_WEBHOOK_URL` only in the current shell, then run:

```bash
vca-reservation test-webhook
```

Expected: exit code 0 and one non-mentioning test message in the target group.

- [ ] **Step 3: Verify first-run and unchanged-run behavior in a temporary state directory**

Run production `run` twice with `VCA_STATE_PATH` pointing to a temporary file and the webhook provided only as a process environment variable.

Expected: first run sends `初始状态`; second run sends `本小时无变化`. Neither message uses `at_all=true`.

- [ ] **Step 4: Verify changed and recovery-changed paths with fixtures**

Run the focused monitor tests that inject empty and open snapshots.

Expected: changed and recovery-changed payloads use `at_all=true`; unchanged and plain recovery payloads use `at_all=false`.

- [ ] **Step 5: Run final clean verification**

```bash
python3 -m pytest -q
python3 -m ruff check .
git diff --check
git status --short
```

Expected: all tests and Ruff pass, no whitespace errors exist, and only intentionally created or modified implementation-plan tracking files remain.

- [ ] **Step 6: Commit verification-driven fixes, if any**

If Step 1-5 required code changes, stage only those paths and commit:

```bash
git commit -m "fix: harden live reservation monitoring"
```

If no files changed, do not create an empty commit.
