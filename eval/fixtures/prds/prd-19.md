# PRD 19: Dark Mode Toggle

## Problem
Users need a reliable **dark mode toggle** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform dark mode toggle successfully (happy path).
- As a user, I see a clear error when dark mode toggle fails due to invalid input.
- As a user, my dark mode toggle action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
