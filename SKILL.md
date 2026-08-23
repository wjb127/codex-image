---
name: codex-image
description: |
  Generate images through Codex OAuth by default, or use Atlas Cloud as an explicit API-key provider.
  기본값은 Codex OAuth이며, 명시적으로 선택하면 Atlas Cloud API도 사용할 수 있다.
  Usage: /codex-image cherry blossom hanok, /codex-image --provider atlas --size 1024x1536 space cat
argument-hint: "[--provider codex|atlas] [--model <atlas-model>] [--size <WxH>] [--quality low|medium|high] [--out <path>] [-n <count>] <image prompt>"
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# codex-image — AI Image Generation via Codex OAuth or Atlas Cloud

Generate images using OpenAI's `gpt-image-2` model through Codex CLI by default.
The optional Atlas Cloud path uses its asynchronous API and requires an API key.

OpenAI Codex CLI의 내장 `image_gen` 도구를 통해 `gpt-image-2` 모델로 이미지를 생성한다.
**API 키 불필요** — Codex OAuth(ChatGPT 로그인) 인증 사용.

## How it works / 동작 원리

```
User prompt → Claude Code (/codex-image)
  → codex exec (OAuth token auto-managed)
    → built-in image_gen tool (gpt-image-2)
      → ~/.codex/generated_images/<session>/
        → copy to project root
```

> **Important**: OAuth tokens cannot call OpenAI REST API directly (returns 401).
> Must go through `codex exec` which handles auth internally.
>
> OAuth 토큰으로 OpenAI REST API 직접 호출 불가 (401 반환).
> 반드시 `codex exec` 경유 — Codex가 내부적으로 인증 처리.

---

## Step 1 — Select Provider / Provider 선택

Use `codex` unless the user explicitly passes `--provider atlas`.

| Provider | Authentication | Behavior |
|----------|----------------|----------|
| `codex` (default) | Codex OAuth | Existing `codex exec` + `image_gen` flow |
| `atlas` | `ATLASCLOUD_API_KEY` | Live catalog/schema validation, one submit per requested image, bounded result polling |

For `atlas`, resolve the bundled script before continuing:

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  _ATLAS_SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/atlas_image.py"
elif [ -f ".claude/skills/codex-image/scripts/atlas_image.py" ]; then
  _ATLAS_SCRIPT=".claude/skills/codex-image/scripts/atlas_image.py"
else
  _ATLAS_SCRIPT="${HOME}/.claude/skills/codex-image/scripts/atlas_image.py"
fi
test -f "${_ATLAS_SCRIPT}" || { echo "Atlas helper not found"; exit 1; }
```

For the default `codex` provider, verify Codex CLI and OAuth:

```bash
which codex 2>/dev/null && codex --version 2>/dev/null || echo "NOT_FOUND"
```

If `NOT_FOUND`, stop:
> "Codex CLI not installed. Run `npm install -g @openai/codex` then `codex login`."
> "Codex CLI 없음. `npm install -g @openai/codex` 후 `codex login` 실행해."

```bash
codex login status 2>&1
```

If not "Logged in":
> "Codex login required. Run `codex login` in terminal. OAuth login enables image generation without API key."
> "Codex 로그인 필요. 터미널에서 `codex login` 실행. OAuth 로그인하면 API 키 없이 이미지 생성 가능."

## Step 2 — Parse Arguments / 인자 파싱

Extract from `$ARGUMENTS`:

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--provider` | `codex`, `atlas` | `codex` | Generation provider / 생성 provider |
| `--model` | live Atlas model ID | `openai/gpt-image-2/text-to-image` | Atlas only; must be present in the live catalog |
| `--size` | `1024x1024`, `1024x1536`, `1536x1024`, `auto` | `1024x1024` | Image dimensions / 이미지 크기 |
| `--quality` | `low`, `medium`, `high`, `auto` | `auto` | Generation quality / 생성 품질 |
| `--out` | directory path | project root | Save location / 저장 위치 |
| `-n` | 1–10 | `1` | Number of images / 생성 장수 |

Remaining text → image prompt / 나머지 텍스트 → 이미지 프롬프트

If prompt is empty, ask via AskUserQuestion:
> "What image should I generate? Enter a prompt."
> "어떤 이미지를 생성할까? 프롬프트를 입력해줘."

## Step 3 — Determine Save Path / 저장 경로 결정

```bash
_PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
_OUT_DIR="${_PROJECT_ROOT}"
_TIMESTAMP=$(date +%Y%m%d-%H%M%S)
_FILENAME="codex-image-${_TIMESTAMP}"
```

- If `--out` specified, use that path / `--out` 지정 시 해당 경로 사용
- Single image: `codex-image-<timestamp>.png`
- Multiple (`-n > 1`): `codex-image-<timestamp>-1.png`, `-2.png`, ...
- Never overwrite existing files / 기존 파일 덮어쓰기 금지

## Step 4 — Generate Image / 이미지 생성

### Codex OAuth (default)

```bash
codex exec "Perform the following tasks:
1. Use the built-in image_gen tool to generate an image.
2. Prompt: '${_PROMPT}'
3. Size: ${_SIZE}
4. Quality: ${_QUALITY}
5. Count: ${_N}
6. Copy the generated image to '${_OUT_DIR}/${_FILENAME}.png'. For multiple images use -1.png, -2.png suffix.
7. Print the saved file path and size." \
  -C "${_PROJECT_ROOT}" \
  -s workspace-write \
  -c 'model_reasoning_effort="medium"' \
  --skip-git-repo-check \
  2>&1
```

timeout: 120000ms (2 min)

### Required flags / 필수 플래그

- `-s workspace-write` — file write permission / 파일 쓰기 권한
- `--skip-git-repo-check` — works outside git repos / git 레포 외부에서도 실행 가능

### Internal flow (Codex side) / 내부 동작 흐름

1. Codex calls built-in `image_gen` tool (gpt-image-2)
2. Image saved to `~/.codex/generated_images/<session-id>/ig_*.png`
3. Codex copies file to specified project path
4. Reports file path and size

### Atlas Cloud (explicit opt-in)

Run a read-only plan first. It fetches the live model catalog and that model's
schema, validates every request field, and prints the current unit and total
price. It does not submit a generation task.

```bash
python3 "${_ATLAS_SCRIPT}" \
  --prompt "${_PROMPT}" \
  --model "${_MODEL:-openai/gpt-image-2/text-to-image}" \
  --size "${_SIZE}" \
  --quality "${_QUALITY}" \
  --out "${_OUT_DIR}" \
  --count "${_N}" \
  --dry-run
```

Show the plan and price to the user. Only after explicit confirmation, rerun
the same command without `--dry-run` and with `--yes`:

```bash
test -n "${ATLASCLOUD_API_KEY:-}" || { echo "ATLASCLOUD_API_KEY is not set"; exit 1; }
python3 "${_ATLAS_SCRIPT}" \
  --prompt "${_PROMPT}" \
  --model "${_MODEL:-openai/gpt-image-2/text-to-image}" \
  --size "${_SIZE}" \
  --quality "${_QUALITY}" \
  --out "${_OUT_DIR}" \
  --count "${_N}" \
  --yes
```

The helper never retries a generation POST. It retries only result GETs with
bounded exponential backoff and saves timestamped files without overwriting.

## Step 5 — Display Result / 결과 출력

```
═══════════════════════════════════════════════
IMAGE GENERATED / 이미지 생성 완료
═══════════════════════════════════════════════
Prompt: <prompt used>
Size: <size>
Quality: <quality>
Count: <n>
Auth: OAuth (ChatGPT) or Atlas Cloud API key
───────────────────────────────────────────────
<saved file path(s)>
═══════════════════════════════════════════════
```

**Always display the generated image using the Read tool.**
**생성된 이미지를 반드시 Read 도구로 표시한다.**

## Step 6 — Follow-up / 후속 안내

- "Run `/codex-image` again to generate another image."
- For Next.js projects: suggest moving to `public/images/` if needed.

## Error Handling / 에러 처리

| Error | Message |
|-------|---------|
| Auth expired | "Codex OAuth expired. Run `codex login` again." / "OAuth 인증 만료. `codex login` 다시 실행." |
| Model access denied | "No access to gpt-image-2. Check your OpenAI plan." / "gpt-image-2 접근 권한 없음. OpenAI 플랜 확인." |
| Timeout (>2min) | "Generation timed out. Try `--quality low`." / "생성 시간 초과. `--quality low`로 재시도." |
| Rate limit | "API rate limited. Wait and retry." / "API 호출 제한. 잠시 후 재시도." |
| Trust error | Check `--skip-git-repo-check` flag or add project to `~/.codex/config.toml` |
| Atlas schema rejection | Choose only values printed by the live schema plan; do not guess or bypass validation |
| Atlas task still pending | Report the prediction ID; do not submit the POST again |

## Rules / 규칙

- Always use the Read tool to display generated images / 생성된 이미지는 반드시 Read로 표시
- Never overwrite existing files — always use timestamped filenames / 기존 파일 덮어쓰기 금지
- Keep Codex OAuth as the default; use Atlas only when explicitly selected
- Never send a Codex OAuth token to Atlas or an Atlas API key to OpenAI
- Never retry an Atlas generation POST; only result GET polling may retry
- Verify prompt intent before generating / 생성 전 프롬프트 의도 확인
