# PRD 13: Address Book

## Problem
Users need a reliable **address book** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform address book successfully (happy path).
- As a user, I see a clear error when address book fails due to invalid input.
- As a user, my address book action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
