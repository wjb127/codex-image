# codex-image

**Claude Code skill for AI image generation via Codex CLI**
**Codex CLI를 통한 AI 이미지 생성 Claude Code 스킬**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Generate images using OpenAI's `gpt-image-2` model through Codex CLI's built-in `image_gen` tool.
**No API key required** — uses Codex OAuth (ChatGPT login) authentication.

OpenAI Codex CLI의 내장 `image_gen` 도구를 통해 `gpt-image-2` 모델로 이미지를 생성합니다.
**API 키 불필요** — Codex OAuth(ChatGPT 로그인) 인증을 사용합니다.

## How it works / 동작 원리

```
/codex-image "cherry blossom hanok"
  → Claude Code invokes codex exec
    → Codex uses built-in image_gen tool (OAuth auth)
      → gpt-image-2 generates image
        → Image saved to your project root
```

> **Key insight**: Codex OAuth tokens cannot call OpenAI REST API directly (returns 401).
> This skill routes through `codex exec` which handles OAuth authentication internally.
>
> Codex OAuth 토큰으로 OpenAI REST API를 직접 호출하면 401 에러가 발생합니다.
> 이 스킬은 `codex exec`를 경유하여 내부적으로 OAuth 인증을 처리합니다.

## Prerequisites / 사전 준비

1. **Claude Code** — [Install](https://docs.anthropic.com/en/docs/claude-code)
2. **Codex CLI** — `npm install -g @openai/codex`
3. **Codex OAuth login** — `codex login` (ChatGPT account)

```bash
# Verify setup / 설치 확인
codex --version
codex login status  # Should show "Logged in using ChatGPT"
```

## Installation / 설치

### Option A: Global skill (all projects) / 전역 스킬

```bash
# Clone to Claude Code skills directory
# Claude Code 스킬 디렉토리에 클론
git clone https://github.com/wjb127/codex-image.git ~/.claude/skills/codex-image
```

### Option B: Project-local skill / 프로젝트 로컬 스킬

```bash
# Clone to project's .claude/skills directory
# 프로젝트의 .claude/skills 디렉토리에 클론
git clone https://github.com/wjb127/codex-image.git .claude/skills/codex-image
```

## Usage / 사용법

In Claude Code, type:

```
/codex-image a red apple on white background
/codex-image --size 1024x1536 futuristic seoul skyline at sunset
/codex-image --quality high --out ./public/images korean hanok with cherry blossoms
/codex-image -n 3 logo variations for a tech startup
```

### Options / 옵션

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--size` | `1024x1024`, `1024x1536`, `1536x1024`, `auto` | `1024x1024` | Image dimensions / 이미지 크기 |
| `--quality` | `low`, `medium`, `high`, `auto` | `auto` | Generation quality / 생성 품질 |
| `--out` | directory path | project root | Save location / 저장 위치 |
| `-n` | 1–10 | `1` | Number of images / 생성 장수 |

### Output / 결과

- Images saved as `codex-image-<YYYYMMDD-HHmmss>.png` in project root (or `--out` path)
- Multiple images: `codex-image-<timestamp>-1.png`, `-2.png`, ...
- Generated image is displayed inline in Claude Code

## Architecture / 구조

```
codex-image/
├── SKILL.md          # Claude Code skill definition / 스킬 정의
├── README.md         # This file / 이 파일
└── LICENSE           # MIT License
```

### Auth Flow / 인증 흐름

```
codex login (one-time)
  → OAuth token stored in ~/.codex/auth.json
    → codex exec reads token automatically
      → Built-in image_gen tool authenticates via OAuth
        → No OPENAI_API_KEY needed
```

### Why not direct API calls? / 왜 직접 API 호출이 안 되나?

Codex OAuth tokens are **session tokens tied to ChatGPT authentication**, not standard OpenAI API keys. The OpenAI REST API (`api.openai.com`) expects `sk-*` format API keys and rejects OAuth tokens with HTTP 401.

Codex OAuth 토큰은 ChatGPT 인증에 연결된 **세션 토큰**이며 표준 OpenAI API 키가 아닙니다. OpenAI REST API(`api.openai.com`)는 `sk-*` 형식의 API 키를 요구하며 OAuth 토큰에는 HTTP 401을 반환합니다.

The `codex exec` command internally bridges this gap by using its own authenticated channel to the image generation service.

`codex exec` 명령은 이미지 생성 서비스에 대한 자체 인증 채널을 사용하여 이 차이를 내부적으로 해결합니다.

## Troubleshooting / 문제 해결

| Issue | Solution |
|-------|----------|
| `NOT_FOUND` | Install Codex: `npm install -g @openai/codex` |
| Auth error | Re-login: `codex login` |
| Trust error | Add `--skip-git-repo-check` or trust project in `~/.codex/config.toml` |
| Timeout | Try `--quality low` for faster generation |
| 401 on API | This is expected — OAuth tokens can't call REST API directly. Use `codex exec` path. |

## License / 라이선스

MIT — see [LICENSE](LICENSE)

## Credits / 크레딧

- Inspired by [daedal](https://github.com/Hostingglobal-Tech/daedal) (Rust CLI for gpt-image-2)
- Built for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill system
