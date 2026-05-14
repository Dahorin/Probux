// ===================================================================
// PROXY SERVER PARA API DO ROBLOX (usando DNS manual)
//
// Executar: node proxy-roblox.js
//
// Este servidor atua como intermediário entre o Probux (Python/Flask)
// e a API do Roblox, evitando bloqueio de IP.
// - Usa DNS público (8.8.8.8, 1.1.1.1) para resolver hostnames
// - Descomprime respostas gzip/deflate automaticamente
// - IMPORTANTE: Se o próprio servidor não consegue resolver DNS,
//   use um Cloudflare Worker em vez deste proxy local.
// ===================================================================

const http = require('http');
const https = require('https');
const zlib = require('zlib');
const dns = require('dns');

const PORT = process.env.PROXY_PORT || 3999;
const MAX_REDIRECTS = 5;

// DNS público como fallback
const DNS_SERVERS = ['8.8.8.8', '1.1.1.1', '208.67.222.222'];

// Cache de DNS
const dnsCache = new Map();
const DNS_TTL = 120000; // 2 minutos

/**
 * Resolve hostname usando servidores DNS públicos.
 * Fallback para resolução do sistema se os servidores públicos falharem.
 */
function resolveHost(hostname) {
    return new Promise((resolve, reject) => {
        // Verifica cache primeiro
        const cached = dnsCache.get(hostname);
        if (cached && (Date.now() - cached.time) < DNS_TTL) {
            return resolve(cached.ip);
        }

        // Tenta com resolvedor customizado (DNS público)
        const resolver = new dns.Resolver();
        resolver.setServers(DNS_SERVERS);

        resolver.resolve4(hostname, (err, addresses) => {
            if (!err && addresses && addresses.length > 0) {
                const ip = addresses[0];
                dnsCache.set(hostname, { ip, time: Date.now() });
                console.log(`[DNS] ${hostname} → ${ip}`);
                return resolve(ip);
            }

            // Fallback: tenta o resolvedor do sistema
            dns.resolve4(hostname, (err2, addrs) => {
                if (!err2 && addrs && addrs.length > 0) {
                    const ip = addrs[0];
                    dnsCache.set(hostname, { ip, time: Date.now() });
                    console.log(`[DNS] ${hostname} → ${ip} (sistema)`);
                    return resolve(ip);
                }

                console.error(`[DNS] Falhou para ${hostname}: ${err2 || err}`);
                reject(new Error(`DNS resolution failed for ${hostname}`));
            });
        });
    });
}

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
 */
function decompressData(data, contentEncoding) {
    if (!data || data.length === 0) return data;

    if (typeof data === 'string') {
        for (let i = 0; i < Math.min(data.length, 100); i++) {
            const c = data.charCodeAt(i);
            if (c < 9 || (c > 13 && c < 32 && !'\t\n\r'.includes(data[i]))) {
                try {
                    return zlib.gunzipSync(Buffer.from(data, 'binary')).toString('utf-8');
                } catch (e) {
                    try {
                        return zlib.inflateRawSync(Buffer.from(data, 'binary')).toString('utf-8');
                    } catch (e2) {
                        return data;
                    }
                }
            }
        }
        return data;
    }

    try {
        if (contentEncoding && contentEncoding.includes('gzip')) return zlib.gunzipSync(data).toString('utf-8');
        if (contentEncoding && contentEncoding.includes('deflate')) return zlib.inflateSync(data).toString('utf-8');
        if (contentEncoding && contentEncoding.includes('br')) return zlib.brotliDecompressSync(data).toString('utf-8');
    } catch (e) {}

    try { return zlib.gunzipSync(data).toString('utf-8'); } catch (e) {}
    try { return zlib.inflateSync(data).toString('utf-8'); } catch (e) {}
    try { return data.toString('utf-8'); } catch (e) {}
    return data.toString('latin1');
}

/**
 * Faz uma requisição HTTP seguindo redirects automaticamente.
 * Usa resolução DNS manual para contornar bloqueios de DNS do servidor.
 */
async function makeRequest(options, body, redirectCount = 0) {
    const isHttps = options.protocol === 'https:';
    const lib = isHttps ? https : http;

    let hostname = options.hostname;
    let ip = hostname;
    let dnsResolved = false;

    try {
        ip = await resolveHost(hostname);
        dnsResolved = true;
    } catch (e) {
        console.error(`[PROXY] DNS falhou para ${hostname}: ${e.message}`);
    }

    const hostHeader = hostname; // Envia Host header com hostname original
    const hostnameForRequest = dnsResolved ? ip : hostname;

    const reqOptions = {
        hostname: hostnameForRequest,
        port: options.port || (isHttps ? 443 : 80),
        path: options.path || '/',
        method: options.method || 'GET',
        headers: { ...options.headers, host: hostHeader },
        timeout: options.timeout || 30000,
    };

    // Para HTTPS com IP direto, desabilita verificação de hostname
    if (isHttps && dnsResolved) {
        reqOptions.rejectUnauthorized = false;
        reqOptions.checkServerIdentity = () => undefined;
    }

    const bodyStr = body ? JSON.stringify(body) : null;
    if (bodyStr && ['POST', 'PUT', 'PATCH'].includes(reqOptions.method)) {
        reqOptions.headers['Content-Length'] = Buffer.byteLength(bodyStr);
    } else if (reqOptions.method !== 'GET') {
        reqOptions.headers['Content-Length'] = 0;
    }

    const startTime = Date.now();

    return new Promise((resolve, reject) => {
        const req = lib.request(reqOptions, (res) => {
            const chunks = [];
            res.on('data', chunk => { chunks.push(chunk); });
            res.on('end', () => {
                const elapsed = Date.now() - startTime;
                const status = res.statusCode;
                const rawData = Buffer.concat(chunks);
                let data = decompressData(rawData, res.headers['content-encoding']);

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
                        console.log(`[PROXY] 🔄 Redirect ${status} (${redirectCount + 1}/${MAX_REDIRECTS}): ${hostname}${options.path} → ${location}`);
                        makeRequest(newOptions, newBody, redirectCount + 1).then(resolve).catch(reject);
                    } catch (e) {
                        resolve({ data, status, headers: res.headers, elapsed, redirectError: e.message });
                    }
                    return;
                }
                resolve({ data, status, headers: res.headers, elapsed });
            });
        });

        req.on('error', err => reject(err));
        req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });

        if (bodyStr && ['POST', 'PUT', 'PATCH'].includes(reqOptions.method)) {
            req.write(bodyStr);
        }
        req.end();
    });
}

// Teste DNS na inicialização
(async () => {
    try {
        const ip = await resolveHost('api.roblox.com');
        console.log(`✅ DNS funcionando: api.roblox.com → ${ip}`);
    } catch (e) {
        console.error(`⚠️  DNS NÃO funciona para api.roblox.com: ${e.message}`);
        console.error(`   Use Cloudflare Worker como alternativa. Veja proxy-cloudflare.js`);
    }
})();

const server = http.createServer(async (req, res) => {
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

            const domain = body.domain || 'api.roblox.com';
            const targetUrl = targetPath.startsWith('http')
                ? targetPath
                : `https://${domain}${targetPath.startsWith('/') ? targetPath : '/' + targetPath}`;

            const parsedUrl = new URL(targetUrl);
            const isHttps = parsedUrl.protocol === 'https:';

            const finalHeaders = { ...BASE_HEADERS, ...extraHeaders };

            const cookie = req.headers['x-roblox-cookie'] || req.headers['cookie'];
            if (cookie) {
                finalHeaders['Cookie'] = `.ROBLOSECURITY=${cookie}`;
            }

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

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
    console.log('========================================');
    console.log('  🔀 Proxy Roblox rodando na porta ' + PORT);
    console.log('  Endpoint: POST http://localhost:' + PORT + '/proxy');
    console.log('  Health:   GET  http://localhost:' + PORT + '/health');
    console.log('========================================');
});