#!/usr/bin/env bash
# Installs the visio-footage skill for Cursor and Claude Code (FTG-010).
#
# It copies tools/footage-skill/visio-footage/ to ~/.claude/skills/visio-footage/ (Cursor and
# Claude Code both read that folder) and writes the full command of the capture tool into the
# copy, in place of {{TOOL}}. Run it again after you edit the skill.
#
# It touches only ~/.claude/skills/visio-footage/. No other skill is read or changed (the
# visio-evidence skill has its own script in tools/evidence-skill/).

set -euo pipefail

SKILL_NAME="visio-footage"
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

# YouTube scans and clips need ffmpeg and ffprobe. Only a warning: images, pages and PDF pages do
# not need them.
MISSING_FFMPEG=""
for media_tool in ffmpeg ffprobe; do
  command -v "${media_tool}" >/dev/null 2>&1 || MISSING_FFMPEG="${MISSING_FFMPEG} ${media_tool}"
done
if [ -n "${MISSING_FFMPEG}" ]; then
  echo "WARNING: not found on the PATH:${MISSING_FFMPEG}. YouTube scans and clips need them: brew install ffmpeg" >&2
fi

TOOL_COMMAND="uv run --project ${CAPTURE_DIR} visio-footage-capture"

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
echo "YouTube scans and clips need ffmpeg and ffprobe:"
echo "  brew install ffmpeg"
echo

# Wikimedia refuses programs that do not say who runs them. The image command reads this
# variable (an email address or a website of yours) and sends it with the request.
if [ -z "${VISIO_FOOTAGE_CONTACT:-}" ]; then
  echo "NOTE: VISIO_FOOTAGE_CONTACT is not set in this shell. Without it, photos from Wikimedia"
  echo "Commons are refused. Set it to your own email address or website, for example by adding"
  echo "this line to ~/.zshenv:"
  echo "  export VISIO_FOOTAGE_CONTACT=\"you@example.com\""
  echo "Then restart Cursor or Claude Code so that it sees the variable."
  echo
fi

echo "Restart Cursor or Claude Code if a session is already open, so that it finds the skill."
