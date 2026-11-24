# eprint-digest

A tool for staying up to date with what's happening on eprint.
Give it filters for keywords and/or authors, and it will pull all updates in a given amount of time, filter them, and send you an email with title, link, authors, and abstract.
Run it locally, or use the setup below to run it on Github Actions.

Requires Python 3.11+. No dependencies.

## Configure

```bash
cp config.example.toml config.toml   # git-ignored; edit filters and email
```

- `keywords`: regexes matched against title + abstract. Case and accents are ignored; use `(?-i:...)` for case-sensitive.
- `authors`: `Lastname` or `Firstname Lastname`, as spelled on ePrint. Case and accents are ignored. Use full names for common surnames: `Li` also matches `Lin`.

A paper is kept if it matches **any** keyword or author. Omit a key to disable that filter.

## Run locally

```bash
python3 main.py -k lattice -a MyFavAuthor          # filters as flags
python3 main.py -c config.toml                   # filters from config
python3 main.py -c config.toml --days 3          # or --since 2026-11-20
python3 main.py -c config.toml --json            # full records as JSON
python3 main.py -c config.toml --preview out.html
```

To send the email, use a Gmail [app password](https://myaccount.google.com/apppasswords) (requires 2-step verification) for the `from` account:

```bash
read -s "EPRINT_DIGEST_SMTP_PASSWORD?App password: "   # zsh; bash: read -sp "App password: " EPRINT_DIGEST_SMTP_PASSWORD
export EPRINT_DIGEST_SMTP_PASSWORD
python3 main.py -c config.toml --send
```

If you're not seeing the email, check your spam folder. First emails may land in spam.

## Run on GitHub Actions

`.github/workflows/digest.yml` sends the digest Mondays at 12:00 UTC. Edit this file to send on the schedule you prefer. In **Settings → Secrets and variables → Actions**, add:

| Name | Type | Value |
|---|---|---|
| `DIGEST_FILTER_CONFIG` | Variable | `[filter]` section of `config.toml` |
| `DIGEST_EMAIL_CONFIG` | Secret | `[email]` section of `config.toml` |
| `SMTP_PASSWORD` | Secret | app password |

Test with **Actions → Weekly ePrint digest → Run workflow**.

Notes:
- Variables appear unmasked in logs, which are public for public repos. Keep addresses in the secret.
- GitHub pauses scheduled workflows after 60 days without commits; re-enable from the Actions tab.
