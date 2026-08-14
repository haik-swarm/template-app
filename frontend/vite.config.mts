import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import Pages from 'vite-plugin-pages';
import tailwindcss from '@tailwindcss/vite';
import terminal from 'vite-plugin-terminal';
import path from 'path';
import os from 'os';
import fs from 'fs';
import crypto from 'crypto';
import { fileURLToPath } from 'url';

// ESM config (.mts): the packaged app's bundled node 20 cannot require() ESM-only plugins like @tailwindcss/vite, so the config itself must load as ESM.
const here = path.dirname(fileURLToPath(import.meta.url));

// Shared, hash-keyed vite optimization cache. Every webapp-template
// workspace shares its node_modules/ via a symlink to OpenSwarm's warm
// cache, AND now shares the optimized-deps output via this cache too —
// keyed on the hash of vite.config.mts + package.json so a real config
// or dep bump invalidates automatically. First workspace ever opened
// pays the ~10–15s MUI pre-bundle; every subsequent workspace reuses
// the same `.vite-cache/deps/` and boots in under a second.
//
// Why this is safe (despite the earlier React-duplicate issue):
//   1. The skill prompt now mandates MUI path-imports — so every
//      workspace ends up with the SAME, small, deduped optimizeDeps
//      set. No more "workspace A pre-bundled @mui/material barrel,
//      workspace B pre-bundled @mui/material/Button — collision."
//   2. resolve.dedupe pins react/react-dom/emotion to single instances
//      from the symlinked node_modules root.
//   3. Vite's own metadata.json swap is atomic, so concurrent boots
//      don't corrupt the cache.
function sharedViteCacheDir(): string {
  let digest = 'fallback';
  try {
    const hasher = crypto.createHash('sha256');
    for (const f of ['vite.config.mts', 'package.json']) {
      const p = path.join(here, f);
      if (fs.existsSync(p)) hasher.update(fs.readFileSync(p));
    }
    digest = hasher.digest('hex').slice(0, 12);
  } catch {
    // Fall through — if hashing fails we still get a stable shared
    // cache, just under one "fallback" key.
  }
  const base = process.env.OPENSWARM_VITE_CACHE_DIR
    || path.join(os.homedir(), '.openswarm', 'cache', 'webapp_template_vite_cache');
  return path.join(base, digest);
}

export default defineConfig(({ mode }) => {
  const backendPort = process.env.BACKEND_PORT;
  const backendEnabled = backendPort && backendPort !== 'NONE';

  return {
    // Relative asset URLs: the built bundle is served under /api/outputs/workspace/<id>/serve/frontend/dist/, where absolute /assets/ paths would 404 (ENG-209 serve-mode).
    base: './',
    cacheDir: sharedViteCacheDir(),
    plugins: [
      react(),
      // Tailwind only styles the vendored tool-ui components (scoped, no preflight); MUI and app styles are untouched.
      tailwindcss(),
      Pages({ dirs: 'src/pages', extensions: ['tsx'] }),
      // vite-plugin-terminal provides a `virtual:terminal/console` module
      // that only exists in dev; loading it during `vite build` errors
      // out, so the End-of-turn build-verify gate would fail on every
      // brand-new workspace.
      ...(mode === 'development'
        ? [terminal({ console: 'terminal', output: ['terminal', 'console'] })]
        : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(here, 'src'),
        '@toolui': path.resolve(here, 'src/toolui'),
      },
      // Force single instances of React and emotion — even if anything
      // tries to resolve them from a deeper node_modules path (which
      // could happen with symlinked node_modules + nested deps), vite
      // pins to the one true copy at the symlinked top-level.
      dedupe: ['react', 'react-dom', '@emotion/react', '@emotion/styled'],
    },
    // Every bare import reachable from src/, declared up front. Vite otherwise
    // discovers deps lazily: the first visit to a page (or the first click that
    // lazy-loads a toolui component) hits an unseen specifier, triggers a
    // re-optimize, and force-reloads the document — which repaints the
    // index.html cold-start splash mid-session. Pre-bundling everything at
    // boot means there is nothing left to discover.
    optimizeDeps: {
      include: [
        'react',
        'react-dom',
        'react-dom/client',
        'react-redux',
        'react-router-dom',
        '@reduxjs/toolkit',
        '@mui/material/styles',
        '@mui/material/Box',
        '@mui/material/Button',
        '@mui/material/Chip',
        '@mui/material/CircularProgress',
        '@mui/material/Collapse',
        '@mui/material/CssBaseline',
        '@mui/material/Dialog',
        '@mui/material/DialogActions',
        '@mui/material/DialogContent',
        '@mui/material/IconButton',
        '@mui/material/LinearProgress',
        '@mui/material/List',
        '@mui/material/ListItemButton',
        '@mui/material/ListItemIcon',
        '@mui/material/ListItemText',
        '@mui/material/Tooltip',
        '@mui/material/Typography',
        '@mui/icons-material/ArrowForward',
        '@mui/icons-material/AutoFixHigh',
        '@mui/icons-material/Cancel',
        '@mui/icons-material/CheckCircle',
        '@mui/icons-material/Close',
        '@mui/icons-material/CloudOff',
        '@mui/icons-material/ContentCopy',
        '@mui/icons-material/DarkMode',
        '@mui/icons-material/ExpandMore',
        '@mui/icons-material/Favorite',
        '@mui/icons-material/Home',
        '@mui/icons-material/LightMode',
        '@mui/icons-material/Refresh',
        '@mui/icons-material/RemoveCircleOutline',
        '@mui/icons-material/Troubleshoot',
        '@radix-ui/react-accordion',
        '@radix-ui/react-avatar',
        '@radix-ui/react-collapsible',
        '@radix-ui/react-dialog',
        '@radix-ui/react-dropdown-menu',
        '@radix-ui/react-label',
        '@radix-ui/react-popover',
        '@radix-ui/react-radio-group',
        '@radix-ui/react-select',
        '@radix-ui/react-separator',
        '@radix-ui/react-slider',
        '@radix-ui/react-slot',
        '@radix-ui/react-switch',
        '@radix-ui/react-tabs',
        '@radix-ui/react-toggle',
        '@radix-ui/react-toggle-group',
        '@radix-ui/react-tooltip',
        // Lazy-loaded by src/toolui/registry.tsx — these are the ones that
        // used to re-optimize on first render of a toolui component.
        '@pierre/diffs',
        '@pierre/diffs/react',
        'shiki',
        'lucide-react',
        'framer-motion',
        'recharts',
        'leaflet',
        'react-leaflet',
        'supercluster',
        'ansi-to-react',
        'class-variance-authority',
        'clsx',
        'tailwind-merge',
        'zod',
      ],
    },
    define: {
      'process.env.BACKEND_ENABLED': JSON.stringify(backendEnabled ? 'true' : ''),
    },
    server: {
      host: '127.0.0.1',
      port: Number(process.env.FRONTEND_PORT) || 3000,
      strictPort: true,
      open: false,
      // Never show Vite's full-screen red error overlay: a transient bad import mid-build (the agent is
      // still writing files) would flash a scary crash screen at the user. Errors still hit the console
      // + terminal.log, which the agent reads to fix; the card shows a clean "building" state instead.
      hmr: { overlay: false },
      proxy: backendEnabled
        ? {
            '/api': {
              target: `http://localhost:${backendPort || 8324}`,
              changeOrigin: true,
            },
          }
        : undefined,
    },
  };
});
