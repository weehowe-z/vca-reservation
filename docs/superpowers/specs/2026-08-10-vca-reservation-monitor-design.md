# VCA Reservation Monitor Design

## Goal

Run a small, reliable monitor on a Linux desktop that checks Van Cleef & Arpels Japan
appointment availability every hour for the six target boutiques in Osaka, Kobe, and
Hiroshima. Notify one SeaTalk group through its incoming webhook when jewelry-viewing
availability status. Every successful hourly check sends a message; changed availability
mentions all group members.

## Scope

The monitor covers these boutiques:

- Osaka - Umeda Hankyu
- Osaka - Osaka Takashimaya
- Osaka - Shinsaibashi
- Kobe - Kobe Daimaru
- Kobe - Hankyu
- Hiroshima - Fukuya Hatchobori

Only sales appointments for `作品を検討 -> ジュエリー` are considered available.
After-sales service slots must not trigger a notification.

The first version does not book appointments, submit personal information, solve CAPTCHA,
or interact with the website UI. It only reads the public availability endpoints used by the
official appointment page and sends notifications.

## Runtime Architecture

The repository contains a Python 3.11+ package with no third-party runtime dependencies.
A `systemd` timer invokes a one-shot command every hour. The command exits after one check;
there is no permanent polling loop.

The service runs as a dedicated Linux user. Mutable state is stored outside the repository at
`/var/lib/vca-reservation/state.json`. Logs go to standard output and standard error so they
are available through `journalctl`.

## Components

### Configuration

Configuration is read from environment variables:

- `SEATALK_WEBHOOK_URL`: required incoming group webhook URL.
- `VCA_STATE_PATH`: optional state file override; defaults to
  `/var/lib/vca-reservation/state.json`.
- `VCA_HTTP_TIMEOUT_SECONDS`: optional positive timeout; defaults to 15 seconds.

The webhook URL is a bearer capability and must never be committed, printed, or included in
exception messages. The SeaTalk event-callback signing secret is unrelated to outgoing
incoming-webhook messages and is not used by this project.

### VCA API client

The client calls the same public Richemont Canvas endpoints used by the official appointment
page:

1. Fetch boutique availability for each configured boutique.
2. Keep dates whose `salesSlotsCount` is greater than zero.
3. Fetch `RICBA_Sales` time slots for those dates.
4. Keep slots that have remaining capacity and are neither blocked nor blocked for web.

All returned times are treated as Japan local time because the official booking interface
renders them that way.

### Snapshot model

A successful run creates a deterministic snapshot keyed by boutique ID. Each boutique holds
its display name, city, and sorted date-to-time mapping. Empty boutiques remain in the
snapshot so disappearance of availability can be detected.

Ordering is stable to make equality checks, logs, and tests deterministic.

### State and change detection

State records:

- the last successful availability snapshot;
- the current consecutive-failure count;
- whether a failure alert has already been sent.

The state file is written atomically through a temporary file plus rename. A failed VCA query
does not replace the last successful availability snapshot.

Notification rules:

- First successful run: send the complete current snapshot, including an explicit no-slot
  message when all boutiques are empty. This establishes the comparison baseline and does not
  mention all group members.
- Later successful run with a changed snapshot: identify added and removed slots, include the
  complete current availability, and mention all group members.
- Later successful run with an unchanged snapshot: send a heartbeat message that explicitly
  says there was no change and includes the complete current availability, without mentioning
  all group members.
- Third consecutive failed run: send one failure notification.
- Further failures: do not repeat the same failure notification.
- First success after an alerted failure: send one recovery notification, then resume normal
  change detection.

If SeaTalk delivery fails, the new snapshot is not committed. The next hourly run retries the
same notification instead of silently losing it.

### SeaTalk notifier

The notifier sends an HTTP `POST` with `Content-Type: application/json` using the SeaTalk
incoming-webhook text shape:

```json
{
  "tag": "text",
  "text": {
    "content": "...",
    "at_all": false
  }
}
```

`text.at_all` is `true` only for an availability-change message. Initial snapshots, unchanged
heartbeats, monitor failures, and recovery messages do not mention all group members.

Messages contain:

- event type: initial snapshot, unchanged heartbeat, availability changed, monitor failure,
  or recovery;
- check time in Japan Standard Time;
- boutique, date, and available time list;
- the official appointment-page URL.

The formatter stays below SeaTalk's text-size limit. If future availability would exceed the
limit, it truncates detail deterministically and tells the user to open the booking page.

## Scheduling and Installation

The repository provides:

- a one-shot `vca-reservation.service` unit;
- an hourly `vca-reservation.timer` with `Persistent=true`, so a missed run executes after the
  machine starts again;
- an installation script that creates the dedicated user and state directory, installs the
  package into a virtual environment, writes systemd units, and enables the timer;
- an example environment file that contains placeholders only.

Installation requires explicit `sudo` execution on the target Linux desktop. Repository tests
and the one-shot monitor command do not require root.

## Error Handling

- Network requests use a finite timeout and descriptive exceptions with secrets redacted.
- HTTP non-success responses and malformed JSON fail the current run.
- A boutique failure fails the complete snapshot; partial results are never treated as a new
  authoritative state.
- The process uses a non-zero exit status on failed checks or failed notification delivery so
  systemd records the run as failed.
- A systemd-level execution lock prevents overlapping runs.

## Testing Strategy

Unit tests use recorded, minimal JSON fixtures rather than the live API. They cover:

- sales-slot filtering versus service-slot filtering;
- blocked, web-blocked, and full time slots;
- deterministic sorting;
- initial, changed, unchanged, failure, and recovery notification decisions;
- SeaTalk `at_all` behavior for changed versus unchanged snapshots;
- atomic state persistence;
- SeaTalk request shape and webhook redaction;
- invalid configuration and malformed upstream responses.

An explicit smoke command performs one real VCA read without sending SeaTalk. A separate
explicit command sends a SeaTalk test message. Tests never access the network.

## Acceptance Criteria

- A manual real-data check reports the six boutiques and matches the official appointment
  page for jewelry availability.
- A SeaTalk test message succeeds without using the event-callback signing secret.
- The first production run sends one snapshot; every later unchanged run sends one heartbeat.
- A fixture-driven availability change sends exactly one change notification with
  `text.at_all=true`.
- Three consecutive fixture-driven failures send exactly one failure notification, followed
  by one recovery notification after success.
- `pytest` and static checks pass.
- The repository contains no webhook URL, callback signing secret, state file, or generated
  runtime log.
