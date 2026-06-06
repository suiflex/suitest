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
