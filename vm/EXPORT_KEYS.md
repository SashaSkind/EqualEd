# Make vast.env for the laptop (agent task)

The laptop app (`vast.py` at the repo root) needs the same keys this VM already has. Write them
into `vast.env` at the **repo root**. `vast.env` is git-ignored. The human copies it to the laptop.

## Rules

- **Never print, echo, cat, log or commit any value.** Values must never appear in your output or
  in this chat. Only write them to the file, and only check variable **names**.
- Never `git add` `vast.env`. Run `git check-ignore vast.env` before you finish; it must print `vast.env`.

## Step 1: write the file (run exactly this from the repo root)

```bash
( set -a; source /config/team-17.config; set +a
  umask 077
  for k in GPU_BEARER_TOKEN INGRESS_URL USERNAME PASSWORD WANDB_API_KEY WANDB_TEAM WANDB_PROJECT; do
    printf '%s=%s\n' "$k" "$(printenv "$k")"
  done > vast.env )
```

## Step 2: check it without showing values

```bash
cut -d= -f1 vast.env                                   # names only
awk -F= '$2==""{print "EMPTY: "$1}' vast.env           # must print nothing
git check-ignore vast.env                              # must print vast.env
```

If a variable is empty, say which one and stop. Do not guess values.

## Step 3: tell the human (do not do this yourself)

Reply with exactly this:

> `vast.env` is ready at the repo root. In a **plain VM terminal** (not this chat), run
> `cat vast.env`, select the lines, press Ctrl+Shift+C, and paste them into `vast.env` in the
> EqualEd folder on your laptop. Then run `rm vast.env` and `clear` on the VM.

Do not commit anything for this task.
