from flask import Flask, request, Response
import requests

app = Flask(__name__)

  # Mapeamento: qual base usar para cada caminho
BASE_URLS = {
      '/v1/purchases': 'https://api.roblox.com',
      '/v1/users': 'https://api.roblox.com',
      '/v2/': 'https://auth.roblox.com',
      '/v1/catalog': 'https://catalog.roblox.com',
      '/v1/user/currency': 'https://economy.roblox.com',
      '/v1/purchases/game-pass': 'https://economy.roblox.com',
  }

@app.route('/proxy/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def proxy(path):
      path = '/' + path

      # Encontra a base correta
      base = 'https://api.roblox.com'
      for prefix, url in BASE_URLS.items():
          if path.startswith(prefix):
              base = url
              break

      target = base + path

      # Copia headers
      headers = {k: v for k, v in request.headers if k.lower() != 'host'}

      # OPTIONS (CORS preflight)
      if request.method == 'OPTIONS':
          return Response('', status=200, headers={
              'Access-Control-Allow-Origin': '*',
              'Access-Control-Allow-Headers': '*',
              'Access-Control-Allow-Methods': '*',
          })

      try:
          resp = requests.request(
              method=request.method,
              url=target,
              headers=headers,
              json=request.get_json(),
              params=request.args,
              timeout=30
          )

          return Response(
              resp.content,
              status=resp.status_code,
              headers={
                  **dict(resp.headers),
                  'Access-Control-Allow-Origin': '*',
                  'Access-Control-Allow-Credentials': 'true',
              }
          )
      except Exception as e:
          return Response(f'{{"error":"{str(e)}"}}', status=500,
                          headers={'Access-Control-Allow-Origin': '*'})

if __name__ == '__main__':
      port = int(__import__('os').environ.get('PORT', 10000))
      app.run(host='0.0.0.0', port=port)