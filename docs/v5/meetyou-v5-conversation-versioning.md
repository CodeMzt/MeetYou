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
- Visible thread history: when a thread has `current_leaf_message_id`, Core returns the parent-chain path from that leaf instead of the old linear message list. This makes restore/checkout projection non-destructive and keeps old messages queryable on their original branch.
- Edit retry: create a new branch and a new user message revision. The original message stays visible on its original branch. When the original message belongs to an active session, Runtime queues a new inbound message event for the edited revision so the normal Run pipeline can produce the retried assistant response on the new branch.

## Migration

Existing V4 linear conversations migrate to a default branch. Existing messages are assigned to that branch in chronological order, with parent pointers filled linearly.

## First-Stage Boundary

The current backend implementation creates durable version records and APIs, projects visible history from the active leaf path, and edit-retry reuses the normal inbound event path when a session is available.

The first frontend slices expose edit-and-retry from persisted user messages plus a compact version control next to the project/thread selectors. The version control can create manual checkpoints, restore to a checkpoint, and checkout a new branch from a checkpoint. These actions call the Core branch/checkpoint APIs and then reload thread history/version state; they do not overwrite original messages or keep a separate local retry tree.

The UI still does not provide a full branch path browser or sibling variant comparison view. Future branch UI must use the same branch/message revision records rather than introducing separate retry state.
