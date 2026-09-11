# Using your Cursor plan instead of an Anthropic key

ShiftLeft's AI steps can run on your Cursor subscription, with no Anthropic API key. These steps are:

- Feature Kickoff: the compliance proposal (step 4) and the analysis (step 7).
- Guided project setup: matching the discovered sources to a team.

Cursor's web API can't answer a prompt, but the Cursor CLI can. The backend starts the CLI for each
AI step and bills the call to the Cursor account signed in on that machine.

**The CLI has to be on the machine that runs the ShiftLeft backend.** For local use, that's your
laptop.

## 1. Check that your company allows it

Company Cursor plans can restrict the CLI and usage-based spend. The CLI uses the same model
requests as the editor, and large analyses are big prompts. If you aren't sure, ask your Cursor
admin first.

## 2. Install the CLI

```bash
curl https://cursor.com/install -fsS | bash
```

This installs `cursor-agent` and `agent` into `~/.local/bin`. ShiftLeft looks there even when it
isn't on your `PATH`. Check the install:

```bash
~/.local/bin/agent --version
```

## 3. Sign in

Pick one.

**A. Your own seat (recommended for local use).** In a terminal:

```bash
agent login     # opens the browser; sign in with your company Cursor account
agent status    # should show you as logged in
agent models    # the models your plan offers
```

The sign-in is stored for your macOS user, so a backend you start as the same user can use it.

**B. An API key**, for a machine where nobody can run `agent login`, such as a shared box. Create a
key in the Cursor dashboard under **API Keys**, then put it in `backend/.env`:

```bash
SHIFTLEFT_CURSOR_API_KEY=key_...
```

ShiftLeft passes it to the CLI as `CURSOR_API_KEY`, and every run bills to whoever owns the key.
It's a secret: keep it in `.env` (git-ignored), never in code.

## 4. Configure ShiftLeft (optional)

With the defaults, the CLI is found and used automatically. You can set these in `backend/.env`:

| Variable | Default | What it does |
|---|---|---|
| `SHIFTLEFT_CURSOR_CLI` | `auto` | `auto` finds the CLI. A path names the binary. `off` turns Cursor off |
| `SHIFTLEFT_CURSOR_MODEL` | empty | The model for steps that have no picker (compliance, guided setup), and the picker's default. Empty means the model `agent models` marks as current. Use an id from `agent models`, e.g. `sonnet-4.5` |
| `SHIFTLEFT_CURSOR_TIMEOUT_SECONDS` | `120` | How long guided setup waits for Cursor |
| `SHIFTLEFT_KICKOFF_MODEL_TIMEOUT_SECONDS` | `300` | How long the kickoff analysis waits (both Claude and Cursor) |

**If both an Anthropic key and Cursor are set up,** the Anthropic key is the default. To make Cursor
the only AI option, leave `SHIFTLEFT_ANTHROPIC_API_KEY` empty.

Restart the backend after changing `.env`.

## 5. Use it

1. Open **Feature Kickoff** and open an analysis (or start one from a PRD link).
2. The status panel lists **AI (the analysis)** as ready, via *Cursor (your Cursor plan)*.
3. On step 7, under **Who drafts it**, choose **Cursor**. Then pick a model from the list, which
   comes live from `agent models`.
4. Click **Run the analysis**. Expect one to three minutes, a bit more than the Anthropic API,
   because each run starts a new agent.
5. The draft is labelled **AI draft**, drafted by *"&lt;model&gt; through Cursor"*. As with Claude,
   nothing counts until a named person creates it in Jira.

Compliance proposals (step 4) and guided setup use Cursor automatically when there's no Anthropic
key. Their labels say *Cursor*.

## What the CLI is allowed to do

The Cursor CLI is a coding agent, so ShiftLeft limits every run:

- `--mode ask`: read-only, so it can't edit files or run commands.
- Each run happens in a new, empty temporary folder, which is deleted afterwards.
- Never `--force` and never `--approve-mcps`, so MCP servers configured in your editor aren't
  approved for these runs.
- The CLI gets only `PATH`, `HOME`, locale settings and its own key. No `SHIFTLEFT_*` setting
  reaches it: no Atlassian, GitHub or Anthropic credentials.
- The PRD, repos and docs are passed as data. The reply must be JSON matching the same schema the
  Anthropic path uses, and it goes through the same clean-up. Unknown repos, PRD lines and
  compliance keys are dropped.
- If the reply isn't usable (wrong shape, timeout, not signed in), you get the rule-based draft,
  labelled with the reason. It's never passed off as AI.

## Troubleshooting

The reason Cursor can't be used is shown under the Cursor option on step 7. The page re-checks
about every 15 seconds while Cursor is unavailable, and every 5 minutes once it works.

| What it says | What to do |
|---|---|
| *The Cursor CLI isn't installed…* | Do step 2. If it's installed somewhere unusual, set `SHIFTLEFT_CURSOR_CLI=/full/path/to/cursor-agent` |
| *The Cursor CLI isn't signed in…* | Run `agent login` as the same user that runs the backend, or set `SHIFTLEFT_CURSOR_API_KEY` |
| *…its model list couldn't be read* | Your CLI version prints models in a format ShiftLeft doesn't recognise. Set `SHIFTLEFT_CURSOR_MODEL` to an id from `agent models` |
| *Cursor couldn't draft this (…didn't answer within 300 seconds)* | Raise `SHIFTLEFT_KICKOFF_MODEL_TIMEOUT_SECONDS`, or pick a faster model |
| *Cursor couldn't draft this (…didn't match the expected shape)* | The model answered in prose instead of JSON. Run again, or pick a stronger model |
| Cursor isn't offered at all | `SHIFTLEFT_CURSOR_CLI` is `off`. The test suite always sets this, so tests never call your CLI or bill your seat |

To try the CLI outside ShiftLeft:

```bash
cd "$(mktemp -d)" && agent -p --output-format json --mode ask --trust --model sonnet-4.5 'Reply with {"ok": true}'
```

## Limits

- **One machine, one account.** For a shared deployment, each person's runs bill to whoever is
  signed in on the server (or owns `SHIFTLEFT_CURSOR_API_KEY`), not to the person clicking Run.
  That's acceptable for local use. Revisit it before a shared beta.
- **Slower than the API**, because each run starts an agent.
- **No output limit or guaranteed format.** The JSON shape is asked for and then checked. It can't
  be enforced the way the Anthropic API enforces it.
