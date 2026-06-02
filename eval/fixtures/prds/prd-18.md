# PRD 18: Export Data

## Problem
Users need a reliable **export data** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform export data successfully (happy path).
- As a user, I see a clear error when export data fails due to invalid input.
- As a user, my export data action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
