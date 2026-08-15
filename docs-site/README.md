# Suitest docs site (M4-14)

Astro + Starlight documentation site.

```bash
cd docs-site
npm install
npm run dev      # local preview
npm run build    # static build → dist/
```

Content lives in `src/content/docs/`. The API reference embeds the live
OpenAPI schema served by the API at `/openapi.json`.

## Release notes are generated

`src/content/docs/docs/changelog.md` is **not** edited by hand:
`scripts/sync-changelog.mjs` builds it from `packages/*/CHANGELOG.md` (the files
release-please writes) plus the current version in each `package.json`. It runs
from `predev` and `prebuild`, so a `npm run dev` or a deploy always picks up the
newest release — shipping a release needs no docs change at all.

The landing hero reads the same `package.json` versions, so it cannot advertise
a version that was never published.

```bash
npm run sync:changelog   # regenerate on demand
```
