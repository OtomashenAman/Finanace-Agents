#!/usr/bin/env bash
# Finance Admin accounts on the server (the password is asked for, never put in a file):
#
#   bash deploy/admin.sh list
#   bash deploy/admin.sh create aman.a@e-solutionsinc.com "Aman Aditya"
#   bash deploy/admin.sh reset-password aman.a@e-solutionsinc.com
#
# Other users, roles and agent access: in the app (Users), signed in as a Finance Admin.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# A terminal: let the password prompt through; piped input (--password-stdin): no terminal
tty=()
[[ -t 0 ]] || tty=(-T)
"${COMPOSE[@]}" exec "${tty[@]}" backend python -m src.app.cli.admin "$@"
