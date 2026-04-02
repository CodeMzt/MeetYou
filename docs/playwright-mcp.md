# Playwright MCP

MeetYou now supports the official Microsoft Playwright MCP server for webpage browsing and extraction.

## What It Adds

- real browser navigation
- page snapshots through the accessibility tree
- clicking, typing, tab management, screenshots
- network log and console inspection

## Local Config

The local runtime config lives in `user/mcp_servers.json` and includes:

- `playwright_web`: official `@playwright/mcp`
- `filesystem_tools`: existing filesystem MCP, now also compatible with Windows `npx.cmd`

## Recommended Usage

For browsing and scraping, the most useful tools are:

- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_wait_for`
- `browser_take_screenshot`

## Stability Rules

- Prefer direct target URLs over search-engine result pages.
- Avoid Google search result pages in browser automation flows.
- Reuse the persistent browser profile under `user/playwright-user-data`.
- Use Playwright for page interaction, not as a generic web search engine.

## Notes

- Browser engine: `msedge`
- Browser profile: persistent local profile
- npm cache: project-local `.npm-cache/`
- package source: `npx @playwright/mcp@latest`
