# @setu/website

The marketing/product site (Epic 7.1) - distinct from `apps/docs` (the Mintlify
documentation site). React + Vite + Tailwind, same stack as `apps/dashboard`.

```bash
pnpm --filter @setu/website dev       # http://localhost:3001
pnpm --filter @setu/website build
pnpm --filter @setu/website typecheck
```

## Not yet deployed

This builds to a static `dist/` (verified: `pnpm build` succeeds), but isn't hosted
anywhere publicly - that needs a domain and a hosting decision (Vercel/Netlify/S3+CDN/etc.)
that hasn't been made. Every number and claim on the page is real and sourced from
this repo (see `PERFORMANCE.md` for the benchmark figures) - update it if those
change rather than letting the site drift from reality.
