// Proxy Roblox API - Cole no Cloudflare Workers
// Workers → Create → paste → Deploy

const ROBLOX_BASE = "https://api.roblox.com";
const ECONOMY_BASE = "https://economy.roblox.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname + url.search;

    // Determina a base correta
    let base;
    if (path.includes("/v1/purchases") || path.includes("/v1/users")) {
      base = ROBLOX_BASE;
    } else if (path.includes("/v1/catalog") || path.includes("/v2/")) {
      base = ECONOMY_BASE;
    } else {
      base = ROBLOX_BASE;
    }

    const targetUrl = base + path;

    // Reenvia a requisição mantendo headers e body
    const newRequest = new Request(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: "follow"
    });

    // Remove header host para usar o do Cloudflare
    newRequest.headers.delete("Host");

    const response = await fetch(newRequest);

    // Reenvia resposta com CORS liberado
    const newResponse = new Response(response.body, response);
    newResponse.headers.set("Access-Control-Allow-Origin", "*");
    newResponse.headers.set("Access-Control-Allow-Headers", "*");
    return newResponse;
  }
};