from flask import Flask, render_template, request, jsonify, send_file
import requests
from datetime import datetime
import json
import io
import os

# ========================================
# CONFIGURAÇÕES
# ========================================

def carregar_configuracoes():
    """Carrega configurações do config.py ou variáveis de ambiente"""
    try:
        from config import MERCADOLIVRE_CONFIG, FLASK_CONFIG, DATABASE_CONFIG
        print("✅ Configurações carregadas do config.py")
        return MERCADOLIVRE_CONFIG, FLASK_CONFIG, DATABASE_CONFIG
    except ImportError:
        print("⚠️  config.py não encontrado - usando variáveis de ambiente")
        
        return (
            {
                'CLIENT_ID': os.getenv('CLIENT_ID', ''),
                'CLIENT_SECRET': os.getenv('CLIENT_SECRET', ''),
                'REDIRECT_URI': os.getenv('REDIRECT_URI', 'http://localhost:5000/callback'),
                'API_BASE_URL': 'https://api.mercadolibre.com',
                'ACCESS_TOKEN': os.getenv('ACCESS_TOKEN', ''),
                'REFRESH_TOKEN': os.getenv('REFRESH_TOKEN', ''),
                'USER_ID': os.getenv('USER_ID', '')
            },
            {
                'DEBUG': os.getenv('DEBUG', 'False').lower() == 'true',
                'HOST': '0.0.0.0',
                'PORT': int(os.getenv('PORT', 5000)),
                'SECRET_KEY': os.getenv('SECRET_KEY', 'change-this-secret-key')
            },
            {
                'MAX_HISTORICO': int(os.getenv('MAX_HISTORICO', 50))
            }
        )

MERCADOLIVRE_CONFIG, FLASK_CONFIG, DATABASE_CONFIG = carregar_configuracoes()

# ========================================
# INICIALIZAÇÃO
# ========================================

app = Flask(__name__)
app.secret_key = FLASK_CONFIG['SECRET_KEY']

historico_buscas = []
access_token = MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN')

# ========================================
# FUNÇÕES AUXILIARES
# ========================================

def obter_access_token():
    """Obtém ou renova access token"""
    global access_token
    
    if MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN'):
        access_token = MERCADOLIVRE_CONFIG['ACCESS_TOKEN']
        print("✅ Usando ACCESS_TOKEN configurado")
        return access_token
    
    if MERCADOLIVRE_CONFIG.get('REFRESH_TOKEN'):
        try:
            response = requests.post(
                f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/oauth/token",
                data={
                    'grant_type': 'refresh_token',
                    'client_id': MERCADOLIVRE_CONFIG['CLIENT_ID'],
                    'client_secret': MERCADOLIVRE_CONFIG['CLIENT_SECRET'],
                    'refresh_token': MERCADOLIVRE_CONFIG['REFRESH_TOKEN']
                },
                timeout=10
            )
            
            if response.status_code == 200:
                access_token = response.json().get('access_token')
                print("✅ Access token renovado com sucesso!")
                return access_token
            else:
                print(f"❌ Erro ao renovar token: {response.status_code}")
        except Exception as e:
            print(f"💥 Erro ao renovar token: {str(e)}")
    
    if MERCADOLIVRE_CONFIG.get('CLIENT_ID') and MERCADOLIVRE_CONFIG.get('CLIENT_SECRET'):
        try:
            response = requests.post(
                f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/oauth/token",
                data={
                    'grant_type': 'client_credentials',
                    'client_id': MERCADOLIVRE_CONFIG['CLIENT_ID'],
                    'client_secret': MERCADOLIVRE_CONFIG['CLIENT_SECRET']
                },
                timeout=10
            )
            
            if response.status_code == 200:
                access_token = response.json().get('access_token')
                print("✅ Access token obtido com client_credentials!")
                return access_token
            else:
                print(f"❌ Erro ao obter token: {response.status_code}")
        except Exception as e:
            print(f"💥 Erro ao obter token: {str(e)}")
    
    return None


def limpar_codigo_mlb(codigo):
    """Remove caracteres inválidos do código MLB"""
    return codigo.replace('-', '').replace(' ', '').strip().upper()


def extrair_info_full(json_api):
    """Extrai informações detalhadas sobre Mercado Envios Full"""
    shipping = json_api.get('shipping', {})
    logistic_type = shipping.get('logistic_type', '')
    tags = shipping.get('tags', [])
    
    is_full = (
        logistic_type in ['fulfillment', 'xd_drop_off', 'cross_docking'] or
        'fulfillment' in tags or
        'full' in str(tags).lower() or
        'mandatory_free_shipping' in tags
    )
    
    tipo_full = 'Não é Full'
    if is_full:
        tipos = {
            'fulfillment': 'Mercado Envios Full',
            'xd_drop_off': 'Full com Cross Docking',
            'cross_docking': 'Cross Docking'
        }
        tipo_full = tipos.get(logistic_type, 'Full (tipo não especificado)')
    
    return {
        'e_full': is_full,
        'tipo_full': tipo_full,
        'logistic_type': logistic_type,
        'tags_envio': tags,
        'frete_gratis': shipping.get('free_shipping', False),
        'modo_envio': shipping.get('mode', ''),
        'metodos_envio': shipping.get('methods', []),
        'store_pick_up': shipping.get('store_pick_up', False),
        'local_pick_up': shipping.get('local_pick_up', False),
        'free_methods': [
            {
                'id': method.get('id'),
                'nome': method.get('name', ''),
                'gratis': method.get('free_shipping', False)
            }
            for method in shipping.get('methods', [])
        ]
    }


def buscar_produto_api(mlb_code):
    """Busca informações do produto na API do Mercado Livre"""
    global access_token, historico_buscas
    
    try:
        url = f"{MERCADOLIVRE_CONFIG['API_BASE_URL']}/items/{mlb_code}"
        print(f"🔍 Buscando: {url}")
        
        if not access_token:
            obter_access_token()
        
        headers = {'Authorization': f"Bearer {access_token}"} if access_token else {}
        print(f"🔑 {'Usando' if access_token else 'Sem'} autenticação")
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 401:
            print("🔄 Token expirado, renovando...")
            if obter_access_token():
                headers = {'Authorization': f"Bearer {access_token}"}
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
            
            if len(historico_buscas) > DATABASE_CONFIG['MAX_HISTORICO']:
                historico_buscas.pop()
            
            return produto
        
        codigos_erro = {
            404: 'Produto não encontrado',
            403: 'Acesso negado - Verifique suas credenciais'
        }
        
        if response.status_code in codigos_erro:
            return {'error': codigos_erro[response.status_code], 'codigo': mlb_code}
        
        return {'error': f'Erro na API: {response.status_code}', 'codigo': mlb_code}
    
    except requests.exceptions.Timeout:
        return {'error': 'Tempo de requisição excedido', 'codigo': mlb_code}
    except requests.exceptions.RequestException as e:
        return {'error': f'Erro de conexão: {str(e)}', 'codigo': mlb_code}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'Erro inesperado: {str(e)}', 'codigo': mlb_code}


def adicionar_cors(response):
    """Adiciona headers CORS à resposta"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    return response


# ========================================
# ROTAS PRINCIPAIS
# ========================================

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
    return jsonify({
        'client_id_configurado': bool(MERCADOLIVRE_CONFIG.get('CLIENT_ID')),
        'client_secret_configurado': bool(MERCADOLIVRE_CONFIG.get('CLIENT_SECRET')),
        'access_token_configurado': bool(MERCADOLIVRE_CONFIG.get('ACCESS_TOKEN')),
        'refresh_token_configurado': bool(MERCADOLIVRE_CONFIG.get('REFRESH_TOKEN')),
        'api_url': MERCADOLIVRE_CONFIG['API_BASE_URL'],
        'tem_access_token': bool(access_token)
    })


@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200


# ========================================
# ROTAS DE EXPORTAÇÃO
# ========================================

@app.route('/json/<mlb_code>')
def json_puro(mlb_code):
    """Retorna apenas o JSON puro do produto"""
    print(f"\n{'='*60}")
    print(f"📊 REQUISIÇÃO JSON PURO")
    print(f"{'='*60}")
    
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return jsonify(produto), 404
    
    json_completo = produto.get('json_completo', produto)
    
    print(f"✅ JSON retornado com sucesso!")
    print(f"{'='*60}\n")
    
    return jsonify(json_completo)


@app.route('/csv/<mlb_code>')
def csv_completo(mlb_code):
    """Retorna dados do produto em formato CSV"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return f"erro\n{produto['error']}", 404, {'Content-Type': 'text/csv; charset=utf-8'}
    
    csv_lines = [
        "campo,valor",
        f"codigo,{produto['id']}",
        f"titulo,\"{produto['titulo']}\"",
        f"preco,{produto['preco']}",
        f"moeda,{produto['moeda']}",
        f"condicao,{produto['condicao']}",
        f"estoque,{produto['estoque']}",
        f"vendidos,{produto['vendidos']}",
        f"categoria,{produto['categoria']}",
        f"status,{produto['status']}",
        f"link,{produto['link']}",
        f"data_consulta,{produto['data_busca']}"
    ]
    
    return '\n'.join(csv_lines), 200, {'Content-Type': 'text/csv; charset=utf-8'}


@app.route('/csv-atributos/<mlb_code>')
def csv_atributos(mlb_code):
    """Retorna TODOS os atributos do produto em CSV"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return f"erro\n{produto['error']}", 404, {'Content-Type': 'text/csv; charset=utf-8'}
    
    csv_lines = [
        "campo,valor",
        f"codigo,{produto['id']}",
        f"titulo,\"{produto['titulo']}\"",
        f"preco,{produto['preco']}",
        f"moeda,{produto['moeda']}",
        f"condicao,{produto['condicao']}",
        f"estoque,{produto['estoque']}",
        f"vendidos,{produto['vendidos']}",
        f"categoria,{produto['categoria']}",
        f"status,{produto['status']}",
        f"link,{produto['link']}"
    ]
    
    for attr in produto.get('atributos', []):
        nome = attr['nome'].replace(',', ';')
        valor = str(attr['valor']).replace(',', ';')
        csv_lines.append(f"\"{nome}\",\"{valor}\"")
    
    for i, img in enumerate(produto.get('imagens', []), 1):
        csv_lines.append(f"imagem_{i},{img}")
    
    csv_lines.append(f"data_consulta,{produto['data_busca']}")
    
    return '\n'.join(csv_lines), 200, {'Content-Type': 'text/csv; charset=utf-8'}


# ========================================
# ROTAS MERCADO ENVIOS FULL
# ========================================

@app.route('/full/<mlb_code>')
def verificar_full(mlb_code):
    """Verifica se o produto é Mercado Envios Full"""
    print(f"\n{'='*60}")
    print(f"🚚 VERIFICAÇÃO MERCADO ENVIOS FULL")
    print(f"{'='*60}")
    
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return adicionar_cors(jsonify(produto)), 404
    
    json_api = produto.get('json_completo', {})
    info_full = extrair_info_full(json_api)
    
    resposta = {
        "codigo": produto['id'],
        "titulo": produto['titulo'],
        "link": produto['link'],
        "full": info_full,
        "resumo": {
            "e_full": info_full['e_full'],
            "tipo": info_full['tipo_full'],
            "frete_gratis": info_full['frete_gratis'],
            "mensagem": f"✅ Este produto É Mercado Envios Full ({info_full['tipo_full']})" if info_full['e_full'] else "❌ Este produto NÃO é Mercado Envios Full"
        }
    }
    
    print(f"🚚 É Full? {info_full['e_full']}")
    print(f"📦 Tipo: {info_full['tipo_full']}")
    print(f"{'='*60}\n")
    
    return adicionar_cors(jsonify(resposta))


@app.route('/csv-full/<mlb_code>')
def csv_com_full(mlb_code):
    """Retorna CSV com informações sobre Full"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return f"erro\n{produto['error']}", 404
    
    json_api = produto.get('json_completo', {})
    info_full = extrair_info_full(json_api)
    
    csv_lines = [
        "campo,valor",
        f"codigo,{produto['id']}",
        f"titulo,\"{produto['titulo']}\"",
        f"preco,{produto['preco']}",
        f"estoque,{produto['estoque']}",
        f"vendidos,{produto['vendidos']}",
        f"e_full,{info_full['e_full']}",
        f"tipo_full,{info_full['tipo_full']}",
        f"frete_gratis,{info_full['frete_gratis']}",
        f"logistic_type,{info_full['logistic_type']}",
        f"modo_envio,{info_full['modo_envio']}",
        f"link,{produto['link']}"
    ]
    
    return '\n'.join(csv_lines), 200, {'Content-Type': 'text/csv; charset=utf-8'}


@app.route('/json-raw/<mlb_code>')
def json_raw(mlb_code):
    """Retorna o JSON COMPLETO e RAW direto da API"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return jsonify(produto), 404
    
    json_completo = produto.get('json_completo', produto)
    
    return adicionar_cors(jsonify(json_completo))


@app.route('/json-completo/<mlb_code>')
def json_completo_tudo(mlb_code):
    """Retorna JSON COMPLETO com TODOS os dados + FULL"""
    print(f"\n{'='*60}")
    print(f"📦 REQUISIÇÃO JSON COMPLETO (TUDO + FULL)")
    print(f"{'='*60}")
    
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return adicionar_cors(jsonify(produto)), 404
    
    json_api = produto.get('json_completo', {})
    info_full = extrair_info_full(json_api)
    
    json_completo = {
        "informacoes_basicas": {
            "codigo": produto['id'],
            "titulo": produto['titulo'],
            "subtitulo": json_api.get('subtitle', ''),
            "link": produto['link'],
            "status": produto['status'],
            "data_criacao": json_api.get('date_created', ''),
            "ultima_atualizacao": json_api.get('last_updated', ''),
            "data_consulta": produto['data_busca']
        },
        
        "preco_estoque": {
            "preco": produto['preco'],
            "preco_original": json_api.get('original_price'),
            "moeda": produto['moeda'],
            "estoque_disponivel": produto['estoque'],
            "quantidade_vendida": produto['vendidos'],
            "aceita_mercado_pago": json_api.get('accepts_mercadopago', False),
            "frete_gratis": json_api.get('shipping', {}).get('free_shipping', False),
            "tipo_listagem": json_api.get('listing_type_id', ''),
            "metodo_compra": json_api.get('buying_mode', '')
        },
        
        "produto": {
            "condicao": produto['condicao'],
            "categoria_id": produto['categoria'],
            "categoria_nome": json_api.get('category_id', ''),
            "garantia": json_api.get('warranty', ''),
            "catalogo_listado": json_api.get('catalog_listing', False),
            "catalogo_produto_id": json_api.get('catalog_product_id', ''),
            "dominio_id": json_api.get('domain_id', ''),
            "tags": json_api.get('tags', []),
            "video_id": json_api.get('video_id', '')
        },
        
        "mercado_envios_full": info_full,
        
        "atributos": produto.get('atributos', []),
        
        "imagens": {
            "total": len(produto.get('imagens', [])),
            "urls": produto.get('imagens', []),
            "thumbnail": json_api.get('thumbnail', ''),
            "imagens_detalhadas": [
                {
                    "id": img.get('id', ''),
                    "url": img.get('url', ''),
                    "secure_url": img.get('secure_url', ''),
                    "size": img.get('size', ''),
                    "max_size": img.get('max_size', ''),
                    "quality": img.get('quality', '')
                }
                for img in json_api.get('pictures', [])
            ]
        },
        
        "vendedor": {
            "id": json_api.get('seller_id'),
            "apelido": json_api.get('seller_address', {}).get('city', {}).get('name', ''),
            "tipo_vendedor": 'Profissional' if json_api.get('official_store_id') else 'Particular',
            "loja_oficial_id": json_api.get('official_store_id'),
            "loja_oficial_nome": json_api.get('official_store_name', ''),
            "reputacao": json_api.get('seller_reputation', {})
        },
        
        "localizacao": {
            "cidade": json_api.get('seller_address', {}).get('city', {}).get('name', ''),
            "estado": json_api.get('seller_address', {}).get('state', {}).get('name', ''),
            "pais": json_api.get('seller_address', {}).get('country', {}).get('name', ''),
            "codigo_postal": json_api.get('seller_address', {}).get('zip_code', ''),
            "endereco_completo": json_api.get('seller_address', {})
        },
        
        "envio": {
            "frete_gratis": json_api.get('shipping', {}).get('free_shipping', False),
            "modo_envio": json_api.get('shipping', {}).get('mode', ''),
            "metodos_disponiveis": json_api.get('shipping', {}).get('methods', []),
            "dimensoes": json_api.get('shipping', {}).get('dimensions', ''),
            "tags_envio": json_api.get('shipping', {}).get('tags', []),
            "logistica": json_api.get('shipping', {}).get('logistic_type', ''),
            "loja_pickup": json_api.get('shipping', {}).get('store_pick_up', False)
        },
        
        "variacoes": [
            {
                "id": var.get('id'),
                "preco": var.get('price'),
                "estoque": var.get('available_quantity'),
                "vendidos": var.get('sold_quantity'),
                "imagem": var.get('picture_ids', []),
                "atributos": var.get('attribute_combinations', [])
            }
            for var in json_api.get('variations', [])
        ] if json_api.get('variations') else [],
        
        "descricao": {
            "tem_descricao": json_api.get('descriptions', []) != [],
            "snapshot": json_api.get('descriptions', [{}])[0] if json_api.get('descriptions') else {}
        },
        
        "estatisticas": {
            "visitas": json_api.get('visits', 0),
            "health": json_api.get('health', 0),
            "catalogo_listado": json_api.get('catalog_listing', False)
        },
        
        "informacoes_adicionais": {
            "site_id": json_api.get('site_id', ''),
            "permalink": json_api.get('permalink', ''),
            "secure_thumbnail": json_api.get('secure_thumbnail', ''),
            "parent_item_id": json_api.get('parent_item_id', ''),
            "differential_pricing": json_api.get('differential_pricing', {}),
            "deal_ids": json_api.get('deal_ids', []),
            "automatic_relist": json_api.get('automatic_relist', False),
            "international_delivery_mode": json_api.get('international_delivery_mode', ''),
            "channels": json_api.get('channels', [])
        },
        
        "json_original_api": json_api
    }
    
    print(f"✅ JSON COMPLETO gerado!")
    print(f"🚚 É Full? {info_full['e_full']} ({info_full['tipo_full']})")
    print(f"{'='*60}\n")
    
    response = adicionar_cors(jsonify(json_completo))
    response.headers.add('Content-Type', 'application/json; charset=utf-8')
    
    return response


@app.route('/json-simplificado/<mlb_code>')
def json_simplificado(mlb_code):
    """Retorna JSON simplificado com apenas os dados principais"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return jsonify(produto), 404
    
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
    
    return jsonify(produto_simplificado)


@app.route('/exibir-json/<mlb_code>')
def exibir_json(mlb_code):
    """Busca e exibe o JSON de um produto diretamente pela URL"""
    mlb_code_limpo = limpar_codigo_mlb(mlb_code)
    produto = buscar_produto_api(mlb_code_limpo)
    
    if 'error' in produto:
        return f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <title>❌ Erro - {mlb_code_limpo}</title>
            <style>
                body {{ font-family: Arial; background: #f44336; color: white; text-align: center; padding: 50px; }}
                h1 {{ font-size: 48px; }}
            </style>
        </head>
        <body>
            <h1>❌ Produto não encontrado</h1>
            <p>{produto['error']}</p>
            <p>Código: {mlb_code_limpo}</p>
            <a href="/" style="color: white;">Voltar</a>
        </body>
        </html>
        """
    
    json_completo = produto.get('json_completo', produto)
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>📦 {produto['titulo'][:50]}</title>
        <style>
            body {{ font-family: Arial; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
            pre {{ background: #252526; padding: 20px; border-radius: 8px; overflow-x: auto; }}
            button {{ background: #0e639c; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; margin: 10px 5px; }}
            button:hover {{ background: #1177bb; }}
        </style>
    </head>
    <body>
        <h1>📦 {produto['titulo']}</h1>
        <button onclick="navigator.clipboard.writeText(document.getElementById('json').textContent)">📋 Copiar</button>
        <button onclick="window.location.href='/exportar-json/{mlb_code_limpo}'">💾 Baixar</button>
        <pre id="json">{json.dumps(json_completo, indent=2, ensure_ascii=False)}</pre>
    </body>
    </html>
    """


# ========================================
# INICIALIZAÇÃO DO SERVIDOR
# ========================================

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
    print("🚚 ROTAS MERCADO ENVIOS FULL ATIVADAS:")
    print("   /full/<mlb_code> - Verificar se é Full")
    print("   /csv-full/<mlb_code> - CSV com info Full")
    print("   /json-completo/<mlb_code> - JSON com tudo + Full")
    print("=" * 60)
    print("⚠️  Pressione CTRL+C para parar o servidor")
    print("=" * 60)
    
    app.run(
        debug=FLASK_CONFIG['DEBUG'],
        host=FLASK_CONFIG['HOST'],
        port=FLASK_CONFIG['PORT']
    )
