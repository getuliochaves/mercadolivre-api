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
        'ACCESS_TOKEN': os.getenv('ACCESS_TOKEN', ''),
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
        url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/items/{mlb_code}"
        print(f"🔍 Buscando: {url}")
        
        if not access_token:
            obter_access_token()
        
        headers = {}
        if access_token:
            headers['Authorization'] = f"Bearer {access_token}"
            print(f"🔑 Usando access token")
        else:
            print(f"⚠️  Sem autenticação (tentando API pública)")
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 401:
            print(f"🔄 Token expirado, tentando renovar...")
            if obter_access_token():
                headers['Authorization'] = f"Bearer {access_token}"
                response = requests.get(url, headers=headers, timeout=10)
                print(f"📊 Novo Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Produto encontrado: {data.get('title', 'N/A')}")
            
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
            
            historico_buscas = [p for p in historico_buscas if p['id'] != produto['id']]
            historico_buscas.insert(0, produto)
            
            max_historico = DATABASE_CONFIG['MAX_HISTORICO']
            if len(historico_buscas) > max_historico:
                historico_buscas.pop()
            
            return produto
        
        elif response.status_code == 404:
            return {'error': 'Produto não encontrado', 'codigo': mlb_code}
        elif response.status_code == 403:
            return {'error': 'Acesso negado - Verifique suas credenciais', 'codigo': mlb_code}
        else:
            return {'error': f'Erro na API: {response.status_code}', 'codigo': mlb_code}
    
    except requests.exceptions.Timeout:
        return {'error': 'Tempo de requisição excedido', 'codigo': mlb_code}
    except requests.exceptions.RequestException as e:
        return {'error': f'Erro de conexão: {str(e)}', 'codigo': mlb_code}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'Erro inesperado: {str(e)}', 'codigo': mlb_code}


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/buscar', methods=['POST'])
def buscar():
    data = request.get_json()
    mlb_code = data.get('mlb_code', '').strip()
    
    if not mlb_code:
        return jsonify({'error': 'Código MLB não fornecido'}), 400
    
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return jsonify(produto), 400
    
    return jsonify(produto)

@app.route('/historico')
def historico():
    return jsonify(historico_buscas)

@app.route('/limpar-historico', methods=['POST'])
def limpar_historico():
    global historico_buscas
    historico_buscas = []
    return jsonify({'success': True, 'message': 'Histórico limpo com sucesso'})

@app.route('/exportar-json/<mlb_code>')
def exportar_json(mlb_code):
    produto = next((p for p in historico_buscas if p['id'] == mlb_code), None)
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado no histórico'}), 404
    
    json_completo = produto.get('json_completo', produto)
    json_str = json.dumps(json_completo, indent=2, ensure_ascii=False)
    json_bytes = io.BytesIO(json_str.encode('utf-8'))
    filename = f"{mlb_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    return send_file(
        json_bytes,
        mimetype='application/json',
        as_attachment=True,
        download_name=filename
    )

@app.route('/visualizar-json/<mlb_code>')
def visualizar_json(mlb_code):
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
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/json/<mlb_code>')
def json_puro(mlb_code):
    """
    Retorna apenas o JSON puro do produto (sem HTML)
    Ideal para importar no Google Sheets ou outras integrações
    Exemplo: https://mercadolivre-api-19r5.onrender.com/json/MLB3885071411
    """
    print(f"\n{'='*60}")
    print(f"📊 REQUISIÇÃO JSON PURO")
    print(f"{'='*60}")
    print(f"📝 Código recebido: '{mlb_code}'")
    
    # Limpar código
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    print(f"🧹 Código limpo: '{mlb_code_limpo}'")
    
    # Buscar produto na API
    produto = buscar_produto_api(mlb_code_limpo)
    
    # Se deu erro, retornar erro em JSON
    if 'error' in produto:
        return jsonify(produto), 404
    
    # Retornar JSON completo
    json_completo = produto.get('json_completo', produto)
    
    print(f"✅ JSON retornado com sucesso!")
    print(f"{'='*60}\n")
    
    return jsonify(json_completo)


@app.route('/json-simplificado/<mlb_code>')
def json_simplificado(mlb_code):
    """
    Retorna JSON simplificado com apenas os dados principais
    Ideal para planilhas (menos dados, mais fácil de trabalhar)
    Exemplo: https://mercadolivre-api-19r5.onrender.com/json-simplificado/MLB3885071411
    """
    print(f"\n{'='*60}")
    print(f"📊 REQUISIÇÃO JSON SIMPLIFICADO")
    print(f"{'='*60}")
    print(f"📝 Código recebido: '{mlb_code}'")
    
    # Limpar código
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    
    # Buscar produto na API
    produto = buscar_produto_api(mlb_code_limpo)
    
    # Se deu erro, retornar erro em JSON
    if 'error' in produto:
        return jsonify(produto), 404
    
    # Criar versão simplificada
    produto_simplificado = {
        'codigo': produto['id'],
        'titulo': produto['titulo'],
        'preco': produto['preco'],
        'moeda': produto['moeda'],
        'condicao': produto['condicao'],
        'estoque': produto['estoque'],
        'vendidos': produto['vendidos'],
        'categoria': produto['categoria'],
        'status': produto['status'],
        'link': produto['link'],
        'imagem_principal': produto['imagens'][0] if produto['imagens'] else '',
        'data_consulta': produto['data_busca']
    }
    
    print(f"✅ JSON simplificado retornado!")
    print(f"{'='*60}\n")
    
    return jsonify(produto_simplificado)


@app.route('/exibir-json/<mlb_code>')
def exibir_json(mlb_code):
    """
    Busca e exibe o JSON de um produto diretamente pela URL
    Exemplo: https://mercadolivre-api-19r5.onrender.com/exibir-json/MLB3885071411
    """
    print(f"\n{'='*60}")
    print(f"🔗 BUSCA VIA URL DINÂMICA")
    print(f"{'='*60}")
    print(f"📝 Código recebido: '{mlb_code}'")
    
    # Limpar código
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    print(f"🧹 Código limpo: '{mlb_code_limpo}'")
    
    # Buscar produto na API
    produto = buscar_produto_api(mlb_code_limpo)
    
    # Se deu erro, exibir página de erro
    if 'error' in produto:
        return f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>❌ Erro - {mlb_code_limpo}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    padding: 20px;
                }}
                .error-container {{
                    background: white;
                    padding: 40px;
                    border-radius: 16px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                    text-align: center;
                    max-width: 500px;
                }}
                .error-icon {{
                    font-size: 80px;
                    margin-bottom: 20px;
                }}
                h1 {{
                    color: #e74c3c;
                    margin: 0 0 10px 0;
                }}
                .error-message {{
                    color: #555;
                    font-size: 18px;
                    margin-bottom: 20px;
                }}
                .code {{
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    font-family: 'Courier New', monospace;
                    color: #333;
                    font-weight: bold;
                    margin-bottom: 20px;
                }}
                .back-button {{
                    display: inline-block;
                    background: #667eea;
                    color: white;
                    padding: 12px 30px;
                    border-radius: 8px;
                    text-decoration: none;
                    font-weight: bold;
                    transition: all 0.3s;
                }}
                .back-button:hover {{
                    background: #764ba2;
                    transform: translateY(-2px);
                    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
                }}
            </style>
        </head>
        <body>
            <div class="error-container">
                <div class="error-icon">❌</div>
                <h1>Produto não encontrado</h1>
                <p class="error-message">{produto['error']}</p>
                <div class="code">Código: {mlb_code_limpo}</div>
                <a href="/" class="back-button">🏠 Voltar para o início</a>
            </div>
        </body>
        </html>
        """
    
    # Se encontrou, exibir JSON formatado
    json_completo = produto.get('json_completo', produto)
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>📦 JSON - {mlb_code_limpo}</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }}
            
            .header {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                margin-bottom: 20px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
                gap: 15px;
            }}
            
            .header h1 {{
                color: #333;
                font-size: 24px;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            
            .product-info {{
                background: rgba(255,255,255,0.95);
                padding: 20px;
                border-radius: 12px;
                margin-bottom: 20px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            }}
            
            .product-info h2 {{
                color: #667eea;
                margin-bottom: 15px;
                font-size: 20px;
            }}
            
            .info-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
            }}
            
            .info-item {{
                background: #f8f9fa;
                padding: 12px;
                border-radius: 8px;
                border-left: 4px solid #667eea;
            }}
            
            .info-label {{
                font-size: 12px;
                color: #666;
                font-weight: bold;
                text-transform: uppercase;
                margin-bottom: 5px;
            }}
            
            .info-value {{
                font-size: 16px;
                color: #333;
                font-weight: bold;
            }}
            
            .buttons {{
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }}
            
            button, .btn {{
                background: #667eea;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                font-weight: bold;
                transition: all 0.3s;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                text-decoration: none;
            }}
            
            button:hover, .btn:hover {{
                background: #764ba2;
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            }}
            
            .btn-success {{
                background: #27ae60;
            }}
            
            .btn-success:hover {{
                background: #229954;
            }}
            
            .btn-secondary {{
                background: #95a5a6;
            }}
            
            .btn-secondary:hover {{
                background: #7f8c8d;
            }}
            
            .json-container {{
                background: #1e1e1e;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3);
                overflow: hidden;
            }}
            
            pre {{
                background: #252526;
                padding: 20px;
                border-radius: 8px;
                overflow-x: auto;
                border: 1px solid #3c3c3c;
                color: #d4d4d4;
                font-family: 'Courier New', monospace;
                font-size: 13px;
                line-height: 1.6;
                max-height: 600px;
                overflow-y: auto;
            }}
            
            .copied {{
                display: none;
                background: #27ae60;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: bold;
                animation: fadeIn 0.3s;
            }}
            
            .copied.show {{
                display: inline-flex;
            }}
            
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(-10px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            .link-box {{
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                margin-top: 20px;
                border: 2px dashed #667eea;
            }}
            
            .link-box p {{
                color: #666;
                margin-bottom: 10px;
                font-weight: bold;
            }}
            
            .link-box input {{
                width: 100%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-family: 'Courier New', monospace;
                font-size: 14px;
            }}
            
            @media (max-width: 768px) {{
                .header {{
                    flex-direction: column;
                    align-items: flex-start;
                }}
                
                .buttons {{
                    width: 100%;
                }}
                
                button, .btn {{
                    flex: 1;
                    justify-content: center;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>
                <span>📦</span>
                <span>{produto['titulo'][:50]}...</span>
            </h1>
            <div class="buttons">
                <button onclick="copiarJSON()">📋 Copiar JSON</button>
                <button onclick="baixarJSON()" class="btn-success">💾 Baixar JSON</button>
                <a href="{produto['link']}" target="_blank" class="btn btn-success">🛒 Ver no ML</a>
                <a href="/" class="btn btn-secondary">🏠 Início</a>
                <span id="copiado" class="copied">✅ Copiado!</span>
            </div>
        </div>
        
        <div class="product-info">
            <h2>ℹ️ Informações do Produto</h2>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Código MLB</div>
                    <div class="info-value">{produto['id']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Preço</div>
                    <div class="info-value">{produto['moeda']} {produto['preco']:,.2f}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Condição</div>
                    <div class="info-value">{produto['condicao']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Estoque</div>
                    <div class="info-value">{produto['estoque']} unidades</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Vendidos</div>
                    <div class="info-value">{produto['vendidos']} unidades</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Status</div>
                    <div class="info-value">{produto['status']}</div>
                </div>
            </div>
            
            <div class="link-box">
                <p>🔗 Link direto para este JSON:</p>
                <input type="text" value="{request.url}" readonly onclick="this.select()">
            </div>
        </div>
        
        <div class="json-container">
            <pre id="json-content">{json.dumps(json_completo, indent=2, ensure_ascii=False)}</pre>
        </div>
        
        <script>
            function copiarJSON() {{
                const jsonText = document.getElementById('json-content').textContent;
                navigator.clipboard.writeText(jsonText).then(() => {{
                    const copiado = document.getElementById('copiado');
                    copiado.classList.add('show');
                    setTimeout(() => {{
                        copiado.classList.remove('show');
                    }}, 2000);
                }});
            }}
            
            function baixarJSON() {{
                const jsonText = document.getElementById('json-content').textContent;
                const blob = new Blob([jsonText], {{ type: 'application/json' }});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = '{mlb_code_limpo}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }}
        </script>
    </body>
    </html>
    """





if __name__ == '__main__':
    print("=" * 60)
    print("🚀 MERCADO LIVRE API - SERVIDOR INICIADO")
    print("=" * 60)
    print(f"📍 Porta: {FLASK_CONFIG['PORT']}")
    print(f"📍 Debug: {FLASK_CONFIG['DEBUG']}")
    print(f"📍 Host: {FLASK_CONFIG['HOST']}")
    print("=" * 60)
    
    print("🔍 VERIFICANDO CONFIGURAÇÕES:")
    print(f"   CLIENT_ID: {'✅' if MERCADOLIVRE_CONFIG.get('CLIENT_ID') else '❌'}")
    print(f"   CLIENT_SECRET: {'✅' if MERCADOLIVRE_CONFIG.get('CLIENT_SECRET') else '❌'}")
    print(f"   ACCESS_TOKEN: {'✅' if MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN') else '❌'}")
    print(f"   REFRESH_TOKEN: {'✅' if MERCADOLIVRE_CONFIG.get('REFRESH_TOKEN') else '❌'}")
    print("=" * 60)
    
    if access_token:
        print("✅ Access token carregado!")
    else:
        print("🔑 Tentando obter access token...")
        obter_access_token()
    
    print("=" * 60)
    print("⚠️  Pressione CTRL+C para parar o servidor")
    print("=" * 60)
    
    app.run(
        debug=FLASK_CONFIG['DEBUG'],
        host=FLASK_CONFIG['HOST'],
        port=FLASK_CONFIG['PORT']
    )
