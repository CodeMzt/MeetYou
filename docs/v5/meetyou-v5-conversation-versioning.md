# MeetYou V5 Conversation Versioning

## Goals

V5 conversation control must be durable, auditable, and non-destructive. Editing or retrying an old message must not overwrite or delete existing messages.

## Data Model

- `Thread.active_branch_id`: current visible branch.
- `Thread.current_leaf_message_id`: current branch leaf.
- `ThreadBranch`: a branch in the thread history tree.
- `Message.parent_message_id`: logical previous message in the branch path.
- `Message.branch_id`: branch where this message was created.
- `Message.revision_of_message_id`: original message when a user edits and retries.
- `Message.variant_index`: sibling variant number.
- `ConversationCheckpoint`: durable pointer to a thread, branch, and message leaf.

## Operations

- Restore checkpoint: update the thread active branch and current leaf pointer. Do not delete messages.
- Checkout checkpoint: create a new branch from the checkpoint and make it active.
- Edit retry: create a new branch and a new user message revision. The original message stays visible on its original branch.

## Migration

Existing V4 linear conversations migrate to a default branch. Existing messages are assigned to that branch in chronological order, with parent pointers filled linearly.

## First-Stage Boundary

The first implementation creates durable version records and APIs. It does not yet rebuild the full UI branch path selector or automatically submit a new model Run after edit retry. That follow-up must use the same branch/message revision records rather than introducing a separate retry state.
