from flask import Flask, request, Response
import requests
import os

app = Flask(__name__)

TARGET = "https://api.roblox.com"

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'])
@app.route('/', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'])
def proxy(path=''):
    # Monta a URL alvo
    if path:
        target = f"{TARGET}/{path}"
    else:
        target = TARGET + "/"

    # Copia headers (exceto Host)
    headers = {k: v for k, v in request.headers if k.lower() != 'host'}

    # Preflight CORS
    if request.method == 'OPTIONS':
        return Response('', status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-CSRF-TOKEN, Cookie, User-Agent, Accept, X-Requested-With',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS, PATCH',
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Max-Age': '86400',
        })

    try:
        resp = requests.request(
            method=request.method,
            url=target,
            headers=headers,
            json=request.get_json(silent=True),
            data=request.get_data(),
            params=request.args,
            timeout=30,
            allow_redirects=False
        )

        # Copia headers da resposta
        resp_headers = dict(resp.headers)

        # Remove headers problemáticos
        for h in ['transfer-encoding', 'content-encoding', 'content-length']:
            resp_headers.pop(h, None)

        # Adiciona CORS
        resp_headers['Access-Control-Allow-Origin'] = '*'
        resp_headers['Access-Control-Allow-Credentials'] = 'true'

        return Response(resp.content, status=resp.status_code, headers=resp_headers)

    except requests.exceptions.Timeout:
        return Response('{"error":"timeout"}', status=504,
                       headers={'Access-Control-Allow-Origin': '*'})
    except requests.exceptions.ConnectionError as e:
        return Response(f'{{"error":"connection_error"}}', status=502,
                       headers={'Access-Control-Allow-Origin': '*'})
    except Exception as e:
        return Response(f'{{"error":"{str(e)}"}}', status=500,
                       headers={'Access-Control-Allow-Origin': '*'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)