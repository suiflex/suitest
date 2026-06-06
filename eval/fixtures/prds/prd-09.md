# PRD 09: Wishlist

## Problem
Users need a reliable **wishlist** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform wishlist successfully (happy path).
- As a user, I see a clear error when wishlist fails due to invalid input.
- As a user, my wishlist action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
