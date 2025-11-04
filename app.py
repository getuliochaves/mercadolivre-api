from flask import Flask, render_template, request, jsonify, send_file
import requests
from datetime import datetime
import json
import io
import os

# ========================================
# CONFIGURAÇÕES - LEITURA DAS VARIÁVEIS
# ========================================

# Tentar carregar do config.py (desenvolvimento local)
try:
    from config import MERCADOLIVRE_CONFIG, FLASK_CONFIG, DATABASE_CONFIG
    print("✅ Configurações carregadas do config.py")
except ImportError:
    print("⚠️  config.py não encontrado - usando variáveis de ambiente")
    
    # CONFIGURAÇÕES DO MERCADO LIVRE (do Render)
    MERCADOLIVRE_CONFIG = {
        'CLIENT_ID': os.getenv('CLIENT_ID', ''),
        'CLIENT_SECRET': os.getenv('CLIENT_SECRET', ''),
        'REDIRECT_URI': os.getenv('REDIRECT_URI', 'http://localhost:5000/callback'),
        'API_BASE_URL': 'https://api.mercadolibre.com',
        'ACCESS_TOKEN': os.getenv('ACCESS_TOKEN', ''),  # Token direto do Render
        'REFRESH_TOKEN': os.getenv('REFRESH_TOKEN', ''),
        'USER_ID': os.getenv('USER_ID', '')
    }
    
    # CONFIGURAÇÕES DO FLASK
    FLASK_CONFIG = {
        'DEBUG': os.getenv('DEBUG', 'False').lower() == 'true',
        'HOST': '0.0.0.0',
        'PORT': int(os.getenv('PORT', 5000)),
        'SECRET_KEY': os.getenv('Key', 'change-this-secret-key')
    }
    
    # CONFIGURAÇÕES DO BANCO/HISTÓRICO
    DATABASE_CONFIG = {
        'MAX_HISTORICO': int(os.getenv('MAX_HISTORICO', 50))
    }

app = Flask(__name__)
app.secret_key = FLASK_CONFIG['SECRET_KEY']

# Armazenamento em memória (histórico de buscas)
historico_buscas = []

# Token de acesso (prioritário: variável de ambiente, senão OAuth)
access_token = MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN')

def obter_access_token():
    """Obtém um access token usando Client Credentials ou Refresh Token"""
    global access_token
    
    # Se já tem token configurado no Render, usar ele
    if MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN'):
        access_token = MERCADOLIVRE_CONFIG['ACCESS_TOKEN']
        print(f"✅ Usando ACCESS_TOKEN do Render")
        return access_token
    
    # Senão, tentar renovar com REFRESH_TOKEN
    if MERCADOLIVRE_CONFIG.get('REFRESH_TOKEN'):
        try:
            url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/oauth/token"
            
            data = {
                'grant_type': 'refresh_token',
                'client_id': MERCADOLIVRE_CONFIG['CLIENT_ID'],
                'client_secret': MERCADOLIVRE_CONFIG['CLIENT_SECRET'],
                'refresh_token': MERCADOLIVRE_CONFIG['REFRESH_TOKEN']
            }
            
            print(f"🔄 Renovando access token com refresh_token...")
            response = requests.post(url, data=data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get('access_token')
                print(f"✅ Access token renovado com sucesso!")
                return access_token
            else:
                print(f"❌ Erro ao renovar token: {response.status_code}")
                print(f"📄 Resposta: {response.text}")
        except Exception as e:
            print(f"💥 Erro ao renovar token: {str(e)}")
    
    # Por último, tentar Client Credentials (acesso público limitado)
    if MERCADOLIVRE_CONFIG.get('CLIENT_ID') and MERCADOLIVRE_CONFIG.get('CLIENT_SECRET'):
        try:
            url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/oauth/token"
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': MERCADOLIVRE_CONFIG['CLIENT_ID'],
                'client_secret': MERCADOLIVRE_CONFIG['CLIENT_SECRET']
            }
            
            print(f"🔑 Obtendo access token com client_credentials...")
            response = requests.post(url, data=data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get('access_token')
                print(f"✅ Access token obtido com sucesso!")
                return access_token
            else:
                print(f"❌ Erro ao obter token: {response.status_code}")
                print(f"📄 Resposta: {response.text}")
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
        if not access_token:
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
        if response.status_code == 401:
            print(f"🔄 Token expirado, tentando renovar...")
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
            
            # REMOVER PRODUTO DUPLICADO DO HISTÓRICO
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
            return {'error': 'Acesso negado - Verifique suas credenciais', 'codigo': mlb_code}
        
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
    produto = next((p for p in historico_buscas if p['id'] == mlb_code), None)
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado no histórico'}), 404
    
    json_completo = produto.get('json_completo', produto)
    json_str = json.dumps(json_completo, indent=2, ensure_ascii=False)
    json_bytes = io.BytesIO(json_str.encode('utf-8'))
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
    produto = next((p for p in historico_buscas if p['id'] == mlb_code), None)
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado no histórico'}), 404
    
    json_completo = produto.get('json_completo', produto)
    
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
        'client_id_configurado': bool(MERCADOLIVRE_CONFIG.get('CLIENT_ID')),
        'client_secret_configurado': bool(MERCADOLIVRE_CONFIG.get('CLIENT_SECRET')),
        'access_token_configurado': bool(MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN')),
        'refresh_token_configurado': bool(MERCADOLIVRE_CONFIG.get('REFRESH_TOKEN')),
        'api_url': MERCADOLIVRE_CONFIG['API_BASE_URL'],
        'tem_access_token': bool(access_token)
    }
    return jsonify(status)

@app.route('/health')
def health():
    """Health check para o Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 MERCADO LIVRE API - SERVIDOR INICIADO")
    print("=" * 60)
    print(f"📍 Porta: {FLASK_CONFIG['PORT']}")
    print(f"📍 Debug: {FLASK_CONFIG['DEBUG']}")
    print(f"📍 Host: {FLASK_CONFIG['HOST']}")
    print("=" * 60)
    
    # Verificar configurações
    print("🔍 VERIFICANDO CONFIGURAÇÕES:")
    print(f"   CLIENT_ID: {'✅ Configurado' if MERCADOLIVRE_CONFIG.get('CLIENT_ID') else '❌ Não configurado'}")
    print(f"   CLIENT_SECRET: {'✅ Configurado' if MERCADOLIVRE_CONFIG.get('CLIENT_SECRET') else '❌ Não configurado'}")
    print(f"   ACCESS_TOKEN: {'✅ Configurado' if MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN') else '❌ Não configurado'}")
    print(
