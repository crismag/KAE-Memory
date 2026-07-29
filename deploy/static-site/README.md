# Static frontend hosting

The workspace is client-side rendered with no JavaScript server runtime
(ADR-0009), so a deployment is a directory of files. Any static host serves it.
Hostinger is the first target; nothing here is specific to it beyond one section.

## Build

```bash
make openapi                       # regenerate the client if the API changed
npm --prefix frontend ci
VITE_API_BASE_URL=https://kae.example.com npm --prefix frontend run build
```

Output is `frontend/dist/`. Upload its **contents**, not the folder.

`VITE_API_BASE_URL` is baked in at build time, because a static host has no
runtime to read configuration from. Changing the API address means rebuilding —
a real constraint, and the reason the same-origin shape below avoids the variable
entirely.

## Two shapes, and they are not equally safe

### Same-origin — recommended

nginx on the EC2 host serves `dist/` **and** proxies `/v1`. The browser sees one
origin.

- no `VITE_API_BASE_URL` — relative paths work;
- no CORS;
- **the API is never directly reachable from the internet.**

Copy the build to `/var/www/kae-memory` and the reverse-proxy example is already
configured for it.

### Split-origin — external static hosting

The frontend is on Hostinger, the API on EC2. This is the shape the deployment
brief asks for, and it has a cost that must be stated plainly:

> **It publishes an API with no authentication.** ADR-0014 defers authentication
> to a later milestone; ADR-0017 permits this shape only behind a network
> allowlist. A browser on another origin can reach the API means *anyone* can.

If you use it:

1. build with `VITE_API_BASE_URL` set to the API's public address;
2. set `KAE_CORS_ORIGINS=https://your-frontend-domain` on the API — it defaults
   to empty, so an unconfigured deployment fails closed rather than open;
3. **restrict the security group** to the addresses that need it. This is the
   only real control; CORS is a browser convention and stops nothing else;
4. serve the API over HTTPS. A browser on an HTTPS page will refuse to call an
   HTTP API anyway;
5. **tear the deployment down after the demonstration.**

## SPA routing

The workspace uses a client-side router: `/projects/{id}` is an application route,
not a file. The host must rewrite unknown paths to `index.html` or every direct
link and refresh returns 404.

**Hostinger** (Apache) — place this `.htaccess` beside `index.html`:

```apache
<IfModule mod_rewrite.c>
  RewriteEngine On
  RewriteBase /
  RewriteRule ^index\.html$ - [L]
  RewriteCond %{REQUEST_FILENAME} !-f
  RewriteCond %{REQUEST_FILENAME} !-d
  RewriteRule . /index.html [L]
</IfModule>
```

Other hosts express the same rule differently — Netlify a `_redirects` file,
nginx `try_files`, S3 an error-document mapping. The requirement is identical.

## What is not committed

`frontend/dist/` is generated and ignored. Committing a build makes the
repository the second source of truth for something the build already
determines, and the two drift the first time someone edits one and not the other.

Uploading is manual for now. Automating it needs a deployment credential, which
needs a secrets decision this milestone does not make.
