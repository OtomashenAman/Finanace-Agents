# Running finance.e-solutionsinc.com

Everything the server needs is in this folder. Run the scripts from the app folder on the
server (the one with `docker-compose.yml`); each one says what it does and stops at the
first problem.

## The pieces

| What | Where |
| --- | --- |
| Code | branch `main` of this repository; the server deploys only `main` |
| Settings | `.env` in the app folder, built by the scripts from `.env.prod` (sent by the Finance AI team through a secure channel, never committed). Don't edit `.env` by hand |
| Stack | `docker-compose.prod.yml`: nginx on 127.0.0.1:8081 (site + `/api`), backend, worker, database. `docker-compose.yml` is for developers' machines |
| Web server | Caddy: HTTPS for finance.e-solutionsinc.com, everything to 127.0.0.1:8081 |
| Database | Postgres in the `db` container, volume `finance-acc-prod_pgdata`, not reachable from outside |
| Backups | `~/finance-acc-backups`, nightly, 14 days |
| Accounts | in the database; Finance Admins manage users in the app (Users) |

## Once: set up the server

1. `git pull`, put `.env.prod` next to `.env`.
2. `bash deploy/fix-now.sh`: the site works again on the current (development) stack.
3. In a quiet window: `bash deploy/migrate-to-prod.sh` (about 10 minutes down), then the Caddy
   change it prints. Trouble: `bash deploy/rollback-to-dev.sh`.
4. `bash deploy/backup-db.sh --install-cron`: nightly backups.
5. Azure network security group: inbound only 443, 80, and 22 from your own IPs.
6. `bash deploy/check.sh`, and send the output to the Finance AI team.

## Every release

```
bash deploy/update.sh
```

Backs up the database, pulls `main`, rebuilds, runs the migrations, checks the site.

## Admin accounts

```
bash deploy/admin.sh list
bash deploy/admin.sh create aman.a@e-solutionsinc.com "Aman Aditya"
bash deploy/admin.sh reset-password aman.a@e-solutionsinc.com
```

The password is typed at the prompt (12+ characters) and given to the person directly; it is
never written to `.env` or any file. Use this for the first admin and when every admin is
locked out; everything else (new users, roles, agent access, resets) is done in the app.

## Database

```
bash deploy/backup-db.sh                      # a backup now (site stays up)
bash deploy/restore-db.sh <file.dump>         # replace the database (asks to type RESTORE)
```

`restore-db.sh` backs up the current database first. Copy backups off the VM regularly
(Azure Blob or another machine).

## Never

- `docker compose down -v` or `docker volume rm`: deletes the database.
- Edit `.env` by hand, or delete `.env.dev-backup` / `.env.generated` (the scripts need them;
  they contain secrets: keep them private).
- Open ports 5437, 8088 or 8081 to the internet.
- Run `docker-compose.yml` again after the move (`rollback-to-dev.sh` is the only way back).
