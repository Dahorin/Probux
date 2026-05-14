// ===================================================================
// PROXY SERVER PARA API DO ROBLOX
//
// Executar: node proxy-roblox.js
//
// Este servidor atua como intermediário entre o Probux (Python/Flask)
// e a API do Roblox, evitando bloqueio de IP.
// - Sigue redirects automaticamente (301, 302, 307, 308)
// - Descomprime respostas gzip/deflate automaticamente
// ===================================================================

const http = require('http');
const https = require('https');
const zlib = require('zlib');

const PORT = process.env.PROXY_PORT || 3999;
const MAX_REDIRECTS = 5;

const BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*;q=0.9',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Origin': 'https://www.roblox.com',
    'Referer': 'https://www.roblox.com/',
    'Connection': 'keep-alive',
};

function parseBody(req) {
    return new Promise((resolve, reject) => {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', () => {
            try { resolve(JSON.parse(body)); }
            catch { resolve({}); }
        });
        req.on('error', reject);
    });
}

/**
 * Decomprime resposta gzip/deflate.
 * Retorna a string descomprimida ou os bytes brutos se não for comprimido.
 */
function decompressData(data, contentEncoding) {
    if (!data || data.length === 0) return data;

    // Se já é string (não comprimido), retornar direto
    if (typeof data === 'string') {
        // Verifica se parece binary garbage
        for (let i = 0; i < Math.min(data.length, 100); i++) {
            const c = data.charCodeAt(i);
            if (c < 9 || (c > 13 && c < 32 && !'\t\n\r'.includes(data[i]))) {
                // Provavelmente binary - tentar descomprimir
                try {
                    const buf = Buffer.from(data, 'binary');
                    const decompressed = zlib.gunzipSync(buf);
                    return decompressed.toString('utf-8');
                } catch (e) {
                    try {
                        const decompressed = zlib.inflateRawSync(buf);
                        return decompressed.toString('utf-8');
                    } catch (e2) {
                        return data; // Não conseguimos descomprimir
                    }
                }
            }
        }
        return data; // Parece ser texto legível
    }

    // Buffer - tentar descomprimir baseado no Content-Encoding
    try {
        if (contentEncoding && contentEncoding.includes('gzip')) {
            return zlib.gunzipSync(data).toString('utf-8');
        }
        if (contentEncoding && contentEncoding.includes('deflate')) {
            return zlib.inflateSync(data).toString('utf-8');
        }
        if (contentEncoding && contentEncoding.includes('br')) {
            return zlib.brotliDecompressSync(data).toString('utf-8');
        }
    } catch (e) {
        // Ignorar erro de descompressão
    }

    // Tentar descomprimir como fallback
    try {
        return zlib.gunzipSync(data).toString('utf-8');
    } catch (e) {
        try {
            return zlib.inflateSync(data).toString('utf-8');
        } catch (e2) {
            try {
                return data.toString('utf-8');
            } catch (e3) {
                return data.toString('latin1');
            }
        }
    }
}

/**
 * Faz uma requisição HTTP seguindo redirects automaticamente.
 * Retorna { data (string descomprimida), status, headers, elapsed }.
 */
function makeRequest(options, body, redirectCount = 0) {
    return new Promise((resolve, reject) => {
        const isHttps = options.protocol === 'https:';
        const lib = isHttps ? https : http;

        const reqOptions = {
            hostname: options.hostname,
            port: options.port || (isHttps ? 443 : 80),
            path: options.path || '/',
            method: options.method || 'GET',
            headers: options.headers || {},
            timeout: options.timeout || 30000,
        };

        const bodyStr = body ? JSON.stringify(body) : null;
        if (bodyStr && ['POST', 'PUT', 'PATCH'].includes(reqOptions.method)) {
            reqOptions.headers['Content-Length'] = Buffer.byteLength(bodyStr);
        } else if (reqOptions.method !== 'GET') {
            reqOptions.headers['Content-Length'] = 0;
        }

        const startTime = Date.now();

        const req = lib.request(reqOptions, (res) => {
            const chunks = [];
            res.on('data', chunk => { chunks.push(chunk); });
            res.on('end', () => {
                const elapsed = Date.now() - startTime;
                const status = res.statusCode;
                const rawData = Buffer.concat(chunks);

                // Descomprime a resposta
                let data = decompressData(rawData, res.headers['content-encoding']);

                // Seguir redirect se aplicável
                if ([301, 302, 307, 308].includes(status) && redirectCount < MAX_REDIRECTS) {
                    const location = res.headers.location;
                    if (!location) {
                        resolve({ data, status, headers: res.headers, elapsed });
                        return;
                    }

                    try {
                        const redirectUrl = new URL(location);
                        const newIsHttps = redirectUrl.protocol === 'https:';

                        let newMethod = options.method;
                        let newBody = body;
                        if ([301, 302, 303].includes(status) && options.method === 'POST') {
                            newMethod = 'GET';
                            newBody = null;
                        }

                        const newOptions = {
                            ...options,
                            protocol: redirectUrl.protocol,
                            hostname: redirectUrl.hostname,
                            port: redirectUrl.port || (newIsHttps ? 443 : 80),
                            path: redirectUrl.pathname + redirectUrl.search,
                            method: newMethod,
                        };

                        newOptions.headers = { ...options.headers };
                        newOptions.headers['host'] = redirectUrl.host;
                        if (newMethod === 'GET') {
                            delete newOptions.headers['content-length'];
                            delete newOptions.headers['content-type'];
                        }

                        console.log(`[PROXY] 🔄 Redirect ${status} (${redirectCount + 1}/${MAX_REDIRECTS}): ${options.hostname}${options.path} → ${location}`);

                        makeRequest(newOptions, newBody, redirectCount + 1)
                            .then(resolve)
                            .catch(reject);
                    } catch (e) {
                        console.error(`[PROXY] Redirect parse error: ${e.message}`);
                        resolve({ data, status, headers: res.headers, elapsed, redirectError: e.message });
                    }
                    return;
                }

                resolve({ data, status, headers: res.headers, elapsed });
            });
        });

        req.on('error', err => reject(err));
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('Request timeout'));
        });

        if (bodyStr && ['POST', 'PUT', 'PATCH'].includes(reqOptions.method)) {
            req.write(bodyStr);
        }

        req.end();
    });
}

const server = http.createServer(async (req, res) => {
    // Health check
    if (req.url === '/health' || req.url === '/') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', message: 'Proxy Roblox ativo', uptime: process.uptime() }));
        return;
    }

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

            // Resolve domínio e URL completa
            const domain = body.domain || 'api.roblox.com';
            const targetUrl = targetPath.startsWith('http')
                ? targetPath
                : `https://${domain}${targetPath.startsWith('/') ? targetPath : '/' + targetPath}`;

            const parsedUrl = new URL(targetUrl);
            const isHttps = parsedUrl.protocol === 'https:';

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
                protocol: parsedUrl.protocol,
                hostname: parsedUrl.hostname,
                port: parsedUrl.port || (isHttps ? 443 : 80),
                path: parsedUrl.pathname + parsedUrl.search,
                method: method,
                headers: finalHeaders,
                timeout: 30000,
            };

            console.log(`[PROXY] → ${method} ${parsedUrl.hostname}${parsedUrl.pathname}`);

            const result = await makeRequest(options, requestBody);

            // Headers de resposta - NÃO repassar Content-Encoding pois já descomprimimos
            res.setHeader('X-Proxy-Status', 'ok');
            res.setHeader('X-Roblox-Status', String(result.status));
            res.setHeader('X-Roblox-Elapsed', result.elapsed + 'ms');
            if (result.headers['content-type']) {
                res.setHeader('Content-Type', result.headers['content-type']);
            }
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
            res.setHeader('Access-Control-Allow-Headers', '*');
            res.writeHead(result.status);
            res.end(result.data);

            console.log(`[PROXY] ← ${result.status} (${result.elapsed}ms) ${parsedUrl.hostname}${parsedUrl.pathname}`);

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
    console.log('  Exemplo: POST { "method": "GET", "url": "/v1/users/authenticated", "domain": "users.roblox.com" }');
    console.log('========================================');
});