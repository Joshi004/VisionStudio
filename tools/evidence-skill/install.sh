#!/usr/bin/env bash
# Installs the visio-evidence skill for Cursor and Claude Code (EVD-005; sound bite claims, SB-004).
#
# It copies tools/evidence-skill/visio-evidence/ to ~/.claude/skills/visio-evidence/ (Cursor and
# Claude Code both read that folder) and writes the full command of the capture tool into the
# copy, in place of {{TOOL}}. Run it again after you edit the skill.
#
# It touches only ~/.claude/skills/visio-evidence/. No other skill is read or changed.

set -euo pipefail

SKILL_NAME="visio-evidence"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
SOURCE_DIR="${SCRIPT_DIR}/${SKILL_NAME}"
CAPTURE_DIR="${REPO_DIR}/tools/evidence-capture"
SKILLS_DIR="${HOME}/.claude/skills"
TARGET_DIR="${SKILLS_DIR}/${SKILL_NAME}"

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

# --- Checks ---------------------------------------------------------------------------------

command -v uv >/dev/null 2>&1 || fail "uv is not installed (https://docs.astral.sh/uv/)."
[ -f "${SOURCE_DIR}/SKILL.md" ] || fail "${SOURCE_DIR}/SKILL.md is missing."
[ -f "${CAPTURE_DIR}/pyproject.toml" ] || fail "${CAPTURE_DIR} is not the capture tool."

# The command is written into the skill and into a permission pattern, so the path may hold only
# plain characters: no spaces, quotes, colons, backslashes or shell characters.
case "${REPO_DIR}" in
  *[!A-Za-z0-9/_.-]*)
    fail "The repository path '${REPO_DIR}' has characters other than letters, digits and / _ . - . Move or link the repository to a plain path and run this again."
    ;;
esac
case "${HOME}" in
  *[!A-Za-z0-9/_.-]*)
    fail "Your home folder path '${HOME}' has characters other than letters, digits and / _ . - ."
    ;;
esac

[ ! -L "${SKILLS_DIR}" ] || fail "${SKILLS_DIR} is a link. Not touching it."
[ ! -L "${TARGET_DIR}" ] || fail "${TARGET_DIR} is a link. Remove the link yourself and run this again."
if [ -e "${TARGET_DIR}" ]; then
  [ -d "${TARGET_DIR}" ] || fail "${TARGET_DIR} exists and is not a folder."
  # Only replace a folder that is this skill.
  grep -q "^name: ${SKILL_NAME}\$" "${TARGET_DIR}/SKILL.md" 2>/dev/null \
    || fail "${TARGET_DIR} exists but is not the ${SKILL_NAME} skill. Not replacing it."
fi

# --- The capture tool's own environment ------------------------------------------------------

echo "Setting up the capture tool (uv sync)..."
uv sync --project "${CAPTURE_DIR}"

# The video command (sound bite claims) needs ffmpeg and ffprobe. Only a warning: web and pdf
# captures do not need them.
MISSING_FFMPEG=""
for media_tool in ffmpeg ffprobe; do
  command -v "${media_tool}" >/dev/null 2>&1 || MISSING_FFMPEG="${MISSING_FFMPEG} ${media_tool}"
done
if [ -n "${MISSING_FFMPEG}" ]; then
  echo "WARNING: not found on the PATH:${MISSING_FFMPEG}. Video captures need them: brew install ffmpeg" >&2
fi

TOOL_COMMAND="uv run --project ${CAPTURE_DIR} visio-evidence-capture"

# --- Build the copy next to its final place, then swap it in ---------------------------------

mkdir -p "${SKILLS_DIR}"
BUILD_DIR="$(mktemp -d "${SKILLS_DIR}/.${SKILL_NAME}.build.XXXXXX")"
OLD_DIR="${SKILLS_DIR}/.${SKILL_NAME}.old.$$"
trap 'rm -rf "${BUILD_DIR}"' EXIT

for source_file in "${SOURCE_DIR}"/*.md; do
  sed "s|{{TOOL}}|${TOOL_COMMAND}|g" "${source_file}" >"${BUILD_DIR}/$(basename "${source_file}")"
done

if grep -q '{{TOOL}}' "${BUILD_DIR}"/*.md; then
  fail "A {{TOOL}} placeholder was left in the copy."
fi

if [ -d "${TARGET_DIR}" ]; then
  mv "${TARGET_DIR}" "${OLD_DIR}"
fi
mv "${BUILD_DIR}" "${TARGET_DIR}"
chmod 755 "${TARGET_DIR}"
rm -rf "${OLD_DIR}"

echo
echo "Installed the ${SKILL_NAME} skill in ${TARGET_DIR}"
echo "The agent will run the capture tool as:"
echo "  ${TOOL_COMMAND}"
echo
echo "If you have not yet, install the browser the tool uses (about 100 MB, once):"
echo "  (cd ${CAPTURE_DIR} && uv run playwright install chromium)"
echo
echo "Video captures (sound bite claims) need ffmpeg and ffprobe:"
echo "  brew install ffmpeg"
echo
echo "Restart Cursor or Claude Code if a session is already open, so that it finds the skill."
