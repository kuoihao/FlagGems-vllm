#!/usr/bin/env bash

# Copyright 2026 FlagOS Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

BACKEND="${1:?usage: $0 <backend>}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must be set}"
: "${RUNNER_TEMP:?RUNNER_TEMP must be set}"
: "${GITHUB_ENV:?GITHUB_ENV must be set}"

if [[ ! "${BACKEND}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Invalid FlagGems backend profile: ${BACKEND}" >&2
  exit 2
fi

workspace="$(cd "${GITHUB_WORKSPACE}" && pwd -P)"
run_id="${GITHUB_RUN_ID:-local}"
run_attempt="${GITHUB_RUN_ATTEMPT:-1}"
state_root="${RUNNER_TEMP}/flaggems-vllm-${run_id}-${run_attempt}-${BACKEND}"

flaggems_dir="${workspace}/.ci/flaggems"
flaggems_venv="${flaggems_dir}/.venv"

# Match FlagGems' own CI by retaining the runner's normal HOME and uv caches.
# Some misconfigured self-hosted runners execute as an unprivileged account
# while inheriting HOME=/root, so fall back first to the account database and
# finally to job-local state only when the normal locations are unusable.
probe_directory() {
  local directory="${1:?}"
  local probe

  mkdir -p "${directory}" 2>/dev/null || return 1
  [[ -d "${directory}" && -w "${directory}" && -x "${directory}" ]] \
    || return 1
  probe="$(mktemp "${directory}/.flaggems-ci-write.XXXXXX" 2>/dev/null)" \
    || return 1
  rm -f -- "${probe}" || return 1
}

usable_home() {
  local candidate="${1:-}"

  [[ -n "${candidate}" && -d "${candidate}" ]] || return 1
  [[ -w "${candidate}" && -x "${candidate}" ]] || return 1
  probe_directory "${candidate}" || return 1
  probe_directory "${candidate}/.local/bin" || return 1
  probe_directory "${candidate}/.cache/uv" || return 1
  probe_directory "${candidate}/.local/share/uv/python" || return 1
}

home_source="inherited"
home_dir="${HOME:-}"
if ! usable_home "${home_dir}"; then
  passwd_home="$({ getent passwd "$(id -u)" 2>/dev/null || true; } \
    | awk -F: 'NR == 1 { print $6 }')"
  home_source="passwd"
  home_dir="${passwd_home}"
fi

if ! usable_home "${home_dir}"; then
  home_source="job-local fallback"
  home_dir="${state_root}/home"
  mkdir -p "${home_dir}/.local/bin"
  usable_home "${home_dir}" || {
    echo "Unable to prepare a writable HOME: ${home_dir}" >&2
    exit 1
  }
fi

home_dir="$(cd "${home_dir}" && pwd -P)"

export HOME="${home_dir}"
export FLAGGEMS_DIR="${flaggems_dir}"
export FLAGGEMS_VENV="${flaggems_venv}"

{
  printf 'HOME=%s\n' "${HOME}"
  printf 'FLAGGEMS_DIR=%s\n' "${FLAGGEMS_DIR}"
  printf 'FLAGGEMS_VENV=%s\n' "${FLAGGEMS_VENV}"
} >> "${GITHUB_ENV}"

echo "Using ${home_source} FlagGems CI HOME: ${HOME}"
