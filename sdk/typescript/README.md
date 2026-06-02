# @suitest/sdk (TypeScript)

Official TypeScript SDK for [Suitest](https://suitest.dev). Dependency-free,
`fetch`-based, works in Node ≥18 and the browser.

```bash
npm install @suitest/sdk
```

```ts
import { SuitestClient } from "@suitest/sdk";

const client = new SuitestClient({
  baseUrl: "https://suitest.example",
  token: process.env.SUITEST_TOKEN,
  workspaceId: "ws_1",
});

const cases = await client.listCases();
const run = await client.createRun({ projectId: "prj_1", name: "smoke", caseIds: [cases[0]!.id] });
const final = await client.waitForRun(run.id);
console.log(final.status);
```

Tracks the OpenAPI schema at `/openapi.json`. Licensed Apache-2.0.
