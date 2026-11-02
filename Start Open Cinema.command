#!/bin/sh
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sh "$project_dir/start-open-cinema.sh" "$@"
result=$?
if [ "$result" -ne 0 ]; then
  printf '\nStartup failed. Press Return to close.'
  read -r response
fi
exit "$result"
