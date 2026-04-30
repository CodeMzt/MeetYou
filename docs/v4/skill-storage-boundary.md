# SKILL Storage Boundary

- SKILL list/detail payloads expose Core-owned storage references such as `core://skills/reusable/task_recognition`.
- Desktop and other endpoint providers must treat those references as remote Core state, not as local file paths to open.
- Assistant SKILL mutations (`create_skill`, `manage_skill`) are Core-side operations.
- Created skills are stored in the Core runtime skill store (`created_skill_dir`, default `user/skills`) instead of the built-in prompt package directory.
