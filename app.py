from flask import Flask, render_template, request, jsonify, send_file
import requests
from datetime import datetime
import json
import io

# Importar configurações
try:
    from config import MERCADOLIVRE_CONFIG, FLASK_CONFIG, DATABASE_CONFIG
    print("✅ Configurações carregadas com sucesso!")
except ImportError:
    print("⚠️  AVISO: Arquivo config.py não encontrado!")
    print("📝 Crie o arquivo config.py com suas credenciais")
    MERCADOLIVRE_CONFIG = {
        'CLIENT_ID': '',
        'CLIENT_SECRET': '',
        'REDIRECT_URI': 'http://localhost:5000/callback',
        'API_BASE_URL': 'https://api.mercadolibre.com'
    }
    FLASK_CONFIG = {
        'DEBUG': True,
        'HOST': '0.0.0.0',
        'PORT': 5000,
        'SECRET_KEY': 'change-this-secret-key'
    }
    DATABASE_CONFIG = {
        'MAX_HISTORICO': 50
    }

app = Flask(__name__)
app.secret_key = FLASK_CONFIG['SECRET_KEY']

# Armazenamento em memória (histórico de buscas)
historico_buscas = []

# Token de acesso (será obtido via OAuth)
access_token = None

def obter_access_token():
    """Obtém um access token usando Client Credentials"""
    global access_token
    
    try:
        url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/oauth/token"
        
        data = {
            'grant_type': 'client_credentials',
            'client_id': MERCADOLIVRE_CONFIG['CLIENT_ID'],
            'client_secret': MERCADOLIVRE_CONFIG['CLIENT_SECRET']
        }
        
        print(f"🔑 Obtendo access token...")
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            print(f"✅ Access token obtido com sucesso!")
            return access_token
        else:
            print(f"❌ Erro ao obter token: {response.status_code}")
            print(f"📄 Resposta: {response.text}")
            return None
            
    except Exception as e:
        print(f"💥 Erro ao obter token: {str(e)}")
        return None

def limpar_codigo_mlb(codigo):
    """Remove hífens e espaços do código MLB"""
    return codigo.replace('-', '').replace(' ', '').strip().upper()

def buscar_produto_api(mlb_code):
    """Busca informações do produto na API do Mercado Livre"""
    global access_token, historico_buscas
    
    try:
        # URL da API do Mercado Livre
        url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/items/{mlb_code}"
        
        print(f"🔍 Buscando: {url}")
        
        # Tentar obter token se não tiver
        if not access_token and MERCADOLIVRE_CONFIG['CLIENT_ID']:
            obter_access_token()
        
        # Headers com autenticação
        headers = {}
        if access_token:
            headers['Authorization'] = f"Bearer {access_token}"
            print(f"🔑 Usando access token")
        else:
            print(f"⚠️  Sem autenticação (tentando API pública)")
        
        # Fazer requisição
        response = requests.get(url, headers=headers, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        
        # Se token expirou (401), tentar renovar
        if response.status_code == 401 and MERCADOLIVRE_CONFIG['CLIENT_ID']:
            print(f"🔄 Token expirado, renovando...")
            if obter_access_token():
                headers['Authorization'] = f"Bearer {access_token}"
                response = requests.get(url, headers=headers, timeout=10)
                print(f"📊 Novo Status Code: {response.status_code}")
        
        # Verificar se a requisição foi bem-sucedida
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Produto encontrado: {data.get('title', 'N/A')}")
            
            # Extrair informações relevantes
            produto = {
                'id': data.get('id'),
                'titulo': data.get('title'),
                'preco': data.get('price'),
                'moeda': data.get('currency_id'),
                'condicao': 'Novo' if data.get('condition') == 'new' else 'Usado',
                'estoque': data.get('available_quantity'),
                'vendidos': data.get('sold_quantity'),
                'categoria': data.get('category_id'),
                'link': data.get('permalink'),
                'imagens': [img['url'] for img in data.get('pictures', [])],
                'atributos': [
                    {'nome': attr['name'], 'valor': attr['value_name']} 
                    for attr in data.get('attributes', [])
                ],
                'status': data.get('status'),
                'data_busca': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'json_completo': data
            }
            
            # ========================================
            # REMOVER PRODUTO DUPLICADO DO HISTÓRICO
            # ========================================
            # Filtrar histórico removendo o produto se já existir
            historico_buscas = [p for p in historico_buscas if p['id'] != produto['id']]
            print(f"🔄 Produto {produto['id']} removido do histórico (se existia)")
            
            # Adicionar produto atualizado no início
            historico_buscas.insert(0, produto)
            print(f"✅ Produto {produto['id']} adicionado no topo do histórico")
            
            # Limitar histórico
            max_historico = DATABASE_CONFIG['MAX_HISTORICO']
            if len(historico_buscas) > max_historico:
                removido = historico_buscas.pop()
                print(f"🗑️  Produto mais antigo removido: {removido['id']}")
            
            print(f"📊 Total de produtos no histórico: {len(historico_buscas)}")
            
            return produto
        
        elif response.status_code == 404:
            print(f"❌ Produto não encontrado: {mlb_code}")
            return {'error': 'Produto não encontrado', 'codigo': mlb_code}
        
        elif response.status_code == 403:
            print(f"🚫 Acesso negado (403)")
            print(f"📄 Resposta: {response.text}")
            return {'error': 'Acesso negado - Verifique suas credenciais no config.py', 'codigo': mlb_code}
        
        else:
            print(f"⚠️  Erro {response.status_code}: {response.text[:200]}")
            return {'error': f'Erro na API: {response.status_code}', 'codigo': mlb_code}
    
    except requests.exceptions.Timeout:
        print(f"⏱️  Timeout na requisição")
        return {'error': 'Tempo de requisição excedido', 'codigo': mlb_code}
    except requests.exceptions.RequestException as e:
        print(f"🌐 Erro de conexão: {str(e)}")
        return {'error': f'Erro de conexão: {str(e)}', 'codigo': mlb_code}
    except Exception as e:
        print(f"💥 Erro inesperado: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'error': f'Erro inesperado: {str(e)}', 'codigo': mlb_code}


@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html')

@app.route('/buscar', methods=['POST'])
def buscar():
    """Endpoint para buscar produto"""
    data = request.get_json()
    mlb_code = data.get('mlb_code', '').strip()
    
    print(f"\n{'='*60}")
    print(f"🔎 NOVA BUSCA RECEBIDA")
    print(f"{'='*60}")
    print(f"📝 Código recebido: '{mlb_code}'")
    
    if not mlb_code:
        print(f"❌ Código vazio!")
        return jsonify({'error': 'Código MLB não fornecido'}), 400
    
    # Limpar código (remover hífens e espaços)
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    print(f"🧹 Código limpo: '{mlb_code_limpo}'")
    
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        print(f"❌ Erro retornado: {produto['error']}")
        print(f"{'='*60}\n")
        return jsonify(produto), 400
    
    print(f"✅ Busca concluída com sucesso!")
    print(f"{'='*60}\n")
    return jsonify(produto)

@app.route('/historico')
def historico():
    """Retorna o histórico de buscas"""
    return jsonify(historico_buscas)

@app.route('/limpar-historico', methods=['POST'])
def limpar_historico():
    """Limpa o histórico de buscas"""
    global historico_buscas
    historico_buscas = []
    return jsonify({'success': True, 'message': 'Histórico limpo com sucesso'})

@app.route('/exportar-json/<mlb_code>')
def exportar_json(mlb_code):
    """Exporta o JSON completo de um produto específico"""
    # Buscar produto no histórico
    produto = next((p for p in historico_buscas if p['id'] == mlb_code), None)
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado no histórico'}), 404
    
    # Pegar o JSON completo da API
    json_completo = produto.get('json_completo', produto)
    
    # Criar arquivo JSON em memória
    json_str = json.dumps(json_completo, indent=2, ensure_ascii=False)
    json_bytes = io.BytesIO(json_str.encode('utf-8'))
    
    # Nome do arquivo
    filename = f"{mlb_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    print(f"📥 Exportando JSON: {filename}")
    
    return send_file(
        json_bytes,
        mimetype='application/json',
        as_attachment=True,
        download_name=filename
    )

@app.route('/visualizar-json/<mlb_code>')
def visualizar_json(mlb_code):
    """Abre o JSON em uma nova aba (formatado)"""
    # Buscar produto no histórico
    produto = next((p for p in historico_buscas if p['id'] == mlb_code), None)
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado no histórico'}), 404
    
    # Pegar o JSON completo da API
    json_completo = produto.get('json_completo', produto)
    
    # Retornar JSON formatado
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>JSON - {mlb_code}</title>
        <style>
            body {{
                font-family: 'Courier New', monospace;
                background: #1e1e1e;
                color: #d4d4d4;
                padding: 20px;
                margin: 0;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: #252526;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            }}
            h1 {{
                color: #4ec9b0;
                margin-top: 0;
            }}
            pre {{
                background: #1e1e1e;
                padding: 20px;
                border-radius: 4px;
                overflow-x: auto;
                border: 1px solid #3c3c3c;
            }}
            .buttons {{
                margin-bottom: 20px;
            }}
            button {{
                background: #0e639c;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                margin-right: 10px;
            }}
            button:hover {{
                background: #1177bb;
            }}
            .copied {{
                display: inline-block;
                margin-left: 10px;
                color: #4ec9b0;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📄 JSON Completo - {mlb_code}</h1>
            <div class="buttons">
                <button onclick="copiarJSON()">📋 Copiar JSON</button>
                <button onclick="baixarJSON()">💾 Baixar JSON</button>
                <span id="copiado" class="copied" style="display:none;">✅ Copiado!</span>
            </div>
            <pre id="json-content">{json.dumps(json_completo, indent=2, ensure_ascii=False)}</pre>
        </div>
        
        <script>
            function copiarJSON() {{
                const jsonText = document.getElementById('json-content').textContent;
                navigator.clipboard.writeText(jsonText).then(() => {{
                    const copiado = document.getElementById('copiado');
                    copiado.style.display = 'inline-block';
                    setTimeout(() => {{
                        copiado.style.display = 'none';
                    }}, 2000);
                }});
            }}
            
            function baixarJSON() {{
                window.location.href = '/exportar-json/{mlb_code}';
            }}
        </script>
    </body>
    </html>
    """

@app.route('/config-status')
def config_status():
    """Verifica status das configurações"""
    status = {
        'client_id_configurado': bool(MERCADOLIVRE_CONFIG['CLIENT_ID']),
        'client_secret_configurado': bool(MERCADOLIVRE_CONFIG['CLIENT_SECRET']),
        'api_url': MERCADOLIVRE_CONFIG['API_BASE_URL'],
        'tem_access_token': bool(access_token)
    }
    return jsonify(status)

# Para funcionar no Render/Heroku
if __name__ == '__main__':
    print("=" * 60)
    print("🚀 MERCADO LIVRE API - SERVIDOR INICIADO")
    print("=" * 60)
    print(f"📍 Acesse: http://localhost:{FLASK_CONFIG['PORT']}")
    print(f"📍 Ou: http://127.0.0.1:{FLASK_CONFIG['PORT']}")
    print("=" * 60)
    
    # Verificar configurações
    if MERCADOLIVRE_CONFIG['CLIENT_ID'] and MERCADOLIVRE_CONFIG['CLIENT_SECRET']:
        print("✅ Credenciais do Mercado Livre configuradas")
        print("🔑 Tentando obter access token...")
        if obter_access_token():
            print("✅ Access token obtido com sucesso!")
        else:
            print("⚠️  Não foi possível obter access token")
    else:
        print("⚠️  Credenciais não configuradas")
    
    print("=" * 60)
    print("⚠️  Pressione CTRL+C para parar o servidor")
    print("=" * 60)
    
    app.run(
        debug=FLASK_CONFIG['DEBUG'],
        host=FLASK_CONFIG['HOST'],
        port=FLASK_CONFIG['PORT']
    )


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 MERCADO LIVRE API - SERVIDOR INICIADO")
    print("=" * 60)
    print(f"📍 Acesse: http://localhost:{FLASK_CONFIG['PORT']}")
    print(f"📍 Ou: http://127.0.0.1:{FLASK_CONFIG['PORT']}")
    print("=" * 60)
    
    # Verificar configurações
    if MERCADOLIVRE_CONFIG['CLIENT_ID'] and MERCADOLIVRE_CONFIG['CLIENT_SECRET']:
        print("✅ Credenciais do Mercado Livre configuradas")
        print("🔑 Tentando obter access token...")
        if obter_access_token():
            print("✅ Access token obtido com sucesso!")
        else:
            print("⚠️  Não foi possível obter access token")
    else:
        print("⚠️  Credenciais não configuradas - configure no config.py")
    
    print("=" * 60)
    print("⚠️  Pressione CTRL+C para parar o servidor")
    print("=" * 60)
    
    app.run(
        debug=FLASK_CONFIG['DEBUG'],
        host=FLASK_CONFIG['HOST'],
        port=FLASK_CONFIG['PORT']
    )
