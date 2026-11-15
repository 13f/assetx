# AssetX frontend

Bun + Vite + Vue 3 + TypeScript + DaisyUI.

```powershell
bun install
bun run dev      # http://127.0.0.1:5173, proxies /api to :8000
bun run build    # type-check + production build to dist/
bun run typecheck
```

The backend serves `dist/` automatically when it exists. See the repository [README](../README.md) and [development guide](../docs/development.md).
