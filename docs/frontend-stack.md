# Frontend stack

[Русская версия](frontend-stack.ru.md)

SaparGuard renders pages and HTML fragments on the server with Jinja2. HTMX 2.x, Alpine CSP,
and Tailwind CSS 4.x are installed from pnpm and copied or built into `app/web/static`; production
does not load frontend code from a CDN or run a Node server.

Approved future dependencies, intentionally not installed yet:

- ECharts — add only with the first working chart;
- Cytoscape.js — add only with the first working relationship graph;
- MapLibre GL JS — add only with the first working map.
