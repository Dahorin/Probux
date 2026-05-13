/**
 * PROXY SERVER PARA API DO ROBLOX
 *
 * Executar: node proxy-roblox.js
 *
 * Este servidor atua como intermediário entre o Probux (Python/Flask)
 * e a API do Roblox, evitando bloqueio de IP.
 *
 * Deploy:
 *   - Opção 1: Executar neste mesmo servidor (mesmo IP)
 *   - Opção 2: Executar em outro servidor/VPS com IP limpo
 *   - Opção 3: Deploy no Railway, Render ou Fly.io
 *
 * Configurar no .env:
 *   ROBLOX_PROXY_URL=http://localhost:3999
 *   (ou a URL do servidor remoto)
 */

const http = require('http');
const https = require('https');
const url = require('url');

const PORT = process.env.PROXY_PORT || 3999;

const BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate',
    'Origin': 'https://www.roblox.com',
    'Referer': 'https://www.roblox.com/',
    'Connection': 'keep-alive',
};

function parseBody(req) {
    return new Promise((resolve, reject) => {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', () => {
            try {
                resolve(JSON.parse(body));
            } catch {
                resolve({});
            }
        });
        req.on('error', reject);
    });
}

const server = http.createServer(async (req, res) => {
    // Health check
    if (req.url === '/health' || req.url === '/') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', message: 'Proxy Roblox ativo', uptime: process.uptime() }));
        return;
    }

    // Apenas POST para /proxy
    if (req.url === '/proxy' || req.url === '/api/proxy' || req.url === '/proxy/') {
        try {
            const body = await parseBody(req);

            let targetPath = body.url || '';
            const method = (body.method || 'GET').toUpperCase();
            const extraHeaders = body.headers || {};
            const requestBody = body.body || null;

            if (!targetPath) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'Faltando parâmetro "url"' }));
                return;
            }

            // Monta URL completa
            const targetUrl = targetPath.startsWith('http')
                ? targetPath
                : `https://api.roblox.com${targetPath.startsWith('/') ? targetPath : '/' + targetPath}`;

            const parsedUrl = new URL(targetUrl);
            const isHttps = parsedUrl.protocol === 'https:';
            const lib = isHttps ? https : http;

            // Monta headers
            const finalHeaders = { ...BASE_HEADERS, ...extraHeaders };

            // Cookie do Roblox
            const cookie = req.headers['x-roblox-cookie'] || req.headers['cookie'];
            if (cookie) {
                finalHeaders['Cookie'] = `.ROBLOSECURITY=${cookie}`;
            }

            // Content-Type para POST
            if (['POST', 'PUT', 'PATCH'].includes(method)) {
                finalHeaders['Content-Type'] = 'application/json; charset=UTF-8';
            }
            delete finalHeaders['host'];
            delete finalHeaders['x-roblox-cookie'];

            const options = {
                hostname: parsedUrl.hostname,
                port: parsedUrl.port || (isHttps ? 443 : 80),
                path: parsedUrl.pathname + parsedUrl.search,
                method: method,
                headers: finalHeaders,
                timeout: 30000,
            };

            const proxyReq = lib.request(options, (proxyRes) => {
                let data = '';
                proxyRes.on('data', chunk => { data += chunk; });
                proxyRes.on('end', () => {
                    res.setHeader('X-Proxy-Status', 'ok');
                    res.setHeader('X-Roblox-Status', String(proxyRes.statusCode));
                    if (proxyRes.headers['content-type']) {
                        res.setHeader('Content-Type', proxyRes.headers['content-type']);
                    }
                    res.setHeader('Access-Control-Allow-Origin', '*');
                    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
                    res.setHeader('Access-Control-Allow-Headers', '*');
                    res.writeHead(proxyRes.statusCode);
                    res.end(data);
                });
            });

            proxyReq.on('error', (err) => {
                console.error('[PROXY] Request error:', err.message);
                res.writeHead(502, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'Proxy error', message: err.message }));
            });

            proxyReq.on('timeout', () => {
                proxyReq.destroy();
                res.writeHead(504, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'Timeout' }));
            });

            if (requestBody && ['POST', 'PUT', 'PATCH'].includes(method)) {
                proxyReq.write(JSON.stringify(requestBody));
            }

            proxyReq.end();

        } catch (error) {
            console.error('[PROXY] Fatal error:', error.message);
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Internal proxy error', message: error.message }));
        }
        return;
    }

    // 404
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
    console.log('========================================');
    console.log('  🔀 Proxy Roblox rodando na porta ' + PORT);
    console.log('  Endpoint: POST http://localhost:' + PORT + '/proxy');
    console.log('  Health:   GET  http://localhost:' + PORT + '/health');
    console.log('  Exemplo: POST { "method": "GET", "url": "/v1/users/authenticated" }');
    console.log('========================================');
});