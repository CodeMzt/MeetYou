# Playwright MCP

MeetYou 当前将 Playwright 浏览器自动化定位为 `Core MCP` 能力，而不是 `Desktop Agent` 本地 MCP。

## What It Adds

- real browser navigation
- page snapshots through the accessibility tree
- clicking, typing, tab management, screenshots
- network log and console inspection

## Config Boundary

- `user/core_mcp_servers.json`: service-side `Core MCP` config, suitable for browser automation and other server-safe integrations
- `user/mcp_servers.json`: Desktop Agent local MCP config, reserved for machine-local capabilities such as filesystem access
- Do not keep Playwright browser automation in Desktop Agent local MCP as the formal path anymore

The example config in this repo uses:

- `browser_automation`: official `@playwright/mcp`
- `filesystem_tools`: a separate Desktop Agent local MCP example kept in `user/mcp_servers.example.json`

## Example Core MCP Config

The browser entry now belongs in `user/core_mcp_servers.json`:

```json
{
  "mcpServers": {
    "browser_automation": {
      "command": "npx",
      "args": [
        "-y",
        "@playwright/mcp@latest",
        "--caps",
        "pdf"
      ],
      "enabled": false
    }
  }
}
```

If you want to keep the Windows desktop browsing experience, you can add Windows-specific flags on that machine, for example `--browser msedge`, `--user-data-dir user/playwright-user-data`, `--output-dir user/playwright-mcp-output`, or a project-local `npm_config_cache`.

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
- Reuse a persistent browser profile such as `user/playwright-user-data` when you need logged-in state.
- Use Playwright for page interaction, not as a generic web search engine.

## Notes

- Browser engine: default browser or an explicit value such as `msedge`
- Browser profile: persistent local profile when needed
- npm cache: optional project-local `.npm-cache/`
- package source: `npx @playwright/mcp@latest`
