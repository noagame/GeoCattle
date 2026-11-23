import { readFile } from 'node:fs/promises';
import { defineConfig, type Connect, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

function localTiles(name: string, route: string, folder: string, tile: RegExp, tileType: string): Plugin {
  const directory = new URL(`../.runtime/${folder}/`, import.meta.url);
  const serveFile: Connect.NextHandleFunction = (request, response) => {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      response.writeHead(405, { Allow: 'GET, HEAD' }).end();
      return;
    }
    const path = request.url?.split('?')[0] ?? '';
    const contentType = path === '/manifest.json' ? 'application/json'
      : path === '/FUENTE.md' ? 'text/plain; charset=utf-8'
        : tile.test(path) ? tileType : undefined;
    if (!contentType) {
      response.writeHead(404).end();
      return;
    }
    readFile(new URL(path.slice(1), directory)).then(
      data => response.writeHead(200, { 'Content-Type': contentType, 'Content-Length': data.length })
        .end(request.method === 'HEAD' ? undefined : data),
      error => response.writeHead(error.code === 'ENOENT' || error.code === 'ENOTDIR' ? 404 : 500).end(),
    );
  };
  return {
    name,
    configureServer(server) { server.middlewares.use(route, serveFile); },
    configurePreviewServer(server) { server.middlewares.use(route, serveFile); },
  };
}

export default defineConfig({
  plugins: [
    react(),
    localTiles('geocattle-local-satellite', '/mapa-local/satelite', 'mapa-satelital', /^\/(?:\d+\/){2}\d+\.webp$/, 'image/webp'),
    localTiles('geocattle-local-osm', '/mapa-local/osm', 'mapa-osm', /^\/(?:\d+\/){2}\d+\.png$/, 'image/png'),
  ],
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } } },
});
