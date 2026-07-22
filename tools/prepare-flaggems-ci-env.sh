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

# Some self-hosted runners execute as an unprivileged account while retaining
# HOME=/root. Keep uv's cache, downloaded Python, and fallback binary install
# in writable job-local storage. This also avoids sharing mutable uv state
# between unrelated fork pull requests on a persistent runner.
home_dir="${state_root}/home"
xdg_cache_dir="${state_root}/xdg-cache"
xdg_data_dir="${state_root}/xdg-data"
uv_cache_dir="${state_root}/uv-cache"
uv_python_dir="${state_root}/uv-python"
flaggems_dir="${workspace}/.ci/flaggems"
flaggems_venv="${flaggems_dir}/.venv"

mkdir -p \
  "${home_dir}/.local/bin" \
  "${xdg_cache_dir}" \
  "${xdg_data_dir}" \
  "${uv_cache_dir}" \
  "${uv_python_dir}"

for directory in \
  "${home_dir}" \
  "${xdg_cache_dir}" \
  "${xdg_data_dir}" \
  "${uv_cache_dir}" \
  "${uv_python_dir}"; do
  if [[ ! -w "${directory}" ]]; then
    echo "CI runtime directory is not writable: ${directory}" >&2
    exit 1
  fi
done

export HOME="${home_dir}"
export XDG_CACHE_HOME="${xdg_cache_dir}"
export XDG_DATA_HOME="${xdg_data_dir}"
export UV_CACHE_DIR="${uv_cache_dir}"
export UV_PYTHON_INSTALL_DIR="${uv_python_dir}"
export FLAGGEMS_DIR="${flaggems_dir}"
export FLAGGEMS_VENV="${flaggems_venv}"

{
  printf 'HOME=%s\n' "${HOME}"
  printf 'XDG_CACHE_HOME=%s\n' "${XDG_CACHE_HOME}"
  printf 'XDG_DATA_HOME=%s\n' "${XDG_DATA_HOME}"
  printf 'UV_CACHE_DIR=%s\n' "${UV_CACHE_DIR}"
  printf 'UV_PYTHON_INSTALL_DIR=%s\n' "${UV_PYTHON_INSTALL_DIR}"
  printf 'FLAGGEMS_DIR=%s\n' "${FLAGGEMS_DIR}"
  printf 'FLAGGEMS_VENV=%s\n' "${FLAGGEMS_VENV}"
} >> "${GITHUB_ENV}"

echo "Prepared isolated FlagGems CI state: ${state_root}"
