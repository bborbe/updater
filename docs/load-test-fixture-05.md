# Update Windows

Updates are applied inside a maintenance window per environment.

## Windows

| Environment | Window | Timezone |
|---|---|---|
| dev | any time | — |
| staging | 06:00–22:00 | UTC |
| prod | 02:00–04:00 | UTC |

The window is evaluated against the wall clock of the controller, not the
target. A controller running in a different timezone shifts every window.

## Behaviour outside the window

An update that falls outside the window is deferred, not dropped. The deferral
is unbounded: if the window never opens, the update waits indefinitely. There is
no alert for a deferral older than 24 hours.

## Overlap

Two updates for the same component can be in flight. The second one wins,
because the apply is last-write-wins on the manifest. This is safe only because
the manifest is derived from the same source of truth.

## Rollback

Rollback uses the previous manifest and is not window-bound. A rollback may
therefore run during peak traffic, which is intentional — correctness beats
timing.
