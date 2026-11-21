# Teacher loop

The teacher is Grok Build. The student is the running `botwidget --dev` local model. A supervisor and a judge are scripts. They share a scoreboard.

The teacher writes the acceptance test, then sends the task through the widget's remote control (`botwidget ask`), the same path as a typed message. The student works only in `/tmp/t-teacher/student`, runs the test, and commits there.

The supervisor cherry-picks that commit into the live checkout only after the suite is green, then restarts the existing `--dev` process (`scripts/botwidget-pc-update`, SIGUSR1). It never starts a second widget. A failed health or smoke check resets the checkout to the last good commit and restarts `--dev` again.

After a restart the student does a dry check: write and read a file in `/tmp`, then read app state. A screenshot is only the fallback.

The judge is not a model. It records tests, health, turn count, and time. A failure summary is the type, the failing test name, and the last error lines.

The teacher gives one hint per retry, at most two retries, then fixes the task and logs a harness improvement.

A task that changes a limit passes the window's values through. `leave_open` takes `LEAVE_GRACE_S`, `LEAVE_MOVING_PX_S` and `LEAVE_MAX_S` from the window. A private copy of the leave cap ignores the test, which sets `LEAVE_MAX_S` to 0, and the bubble tests stay open.

Stop when retries are spent, the PC is going off, or the run grows large. Record that stop on the scoreboard.
