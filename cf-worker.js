// ============================================
// Cloudflare Worker - Proxy para API do Roblox
// Cole este código no dashboard do Cloudflare Workers
// ============================================

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)
  const target = url.searchParams.get('url')

  if (!target) {
    return new Response(JSON.stringify({ error: 'Missing url parameter' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    })
  }

  // Reconstroi a URL alvo
  const targetUrl = decodeURIComponent(target)

  // Clona os headers do request original
  const headers = new Headers(request.headers)

  // Remove headers que podem causar problemas
  headers.delete('Host')
  headers.delete('CF-Connecting-IP')
  headers.delete('CF-Ray')
  headers.delete('CF-Visitor')
  headers.delete('X-Forwarded-For')
  headers.delete('X-Forwarded-Proto')
  headers.delete('X-Real-IP')

  // Adiciona headers realistas
  headers.set('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36')
  headers.set('Accept', 'application/json, text/plain, */*')
  headers.set('Accept-Language', 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7')

  try {
    // Faz a requisição para o Roblox passando todos os parâmetros
    const init = {
      method: request.method,
      headers: headers,
      redirect: 'follow'
    }

    // Adiciona body apenas para POST/PUT/PATCH
    if (['POST', 'PUT', 'PATCH'].includes(request.method)) {
      try {
        const body = await request.text()
        init.body = body
      } catch (e) {}
    }

    const response = await fetch(targetUrl, init)

    // Reconstroi a resposta
    const responseHeaders = new Headers(response.headers)
    responseHeaders.set('Access-Control-Allow-Origin', '*')
    responseHeaders.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    responseHeaders.set('Access-Control-Allow-Headers', '*')

    const responseBody = await response.text()

    return new Response(responseBody, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders
    })
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}