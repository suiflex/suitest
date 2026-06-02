# PRD 06: Add To Cart

## Problem
Users need a reliable **add to cart** capability that works on web and degrades gracefully on errors.

## User stories
- As a user, I can perform add to cart successfully (happy path).
- As a user, I see a clear error when add to cart fails due to invalid input.
- As a user, my add to cart action is rejected when I am not authenticated.

## Acceptance
- Happy path returns success state.
- Invalid input shows a validation error.
- Unauthorized attempt is blocked.
