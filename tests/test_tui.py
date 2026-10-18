"""Regressão da TUI curses, dirigida por teclado num pseudo-terminal.

Cada cenário grava num golden as telas (texto + mapa de estilos) depois de cada
passo relevante, e, quando há save, o estado final de data/.
"""
import subprocess

from support import assert_golden, strip_ansi


def finish(app, tui, name, with_data=True):
    text = tui.golden()
    if with_data:
        text += '\n' + app.data_snapshot()
    assert_golden(f'tui/{name}.txt', text)


# ── Navegação ────────────────────────────────────────────────────────────────

def test_tabs_and_scroll(demo, tui_factory):
    t = tui_factory()
    t.snap('início (Sumário)')
    for key, label in (('r', 'Rentabilidade'), ('a', 'Alocação'), ('i', 'Indexador'), ('o', 'Objetivo'),
                       ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')):
        t.press(key).snap(label)
    t.press('j', 'j', 'j').snap('Gráficos após j j j')
    t.press('k').snap('Gráficos após k')
    t.press('pgdn').snap('Gráficos após PgDn')
    t.press('pgup').snap('Gráficos após PgUp')
    t.press(' ').snap('Gráficos após espaço')
    t.press('G').snap('Gráficos após G (fim)')
    t.press('home').snap('Gráficos após Home (topo)')
    t.press('end').snap('Gráficos após End (fim)')
    t.press('s').snap('volta ao Sumário (scroll zerado)')
    t.press('x', 'z').snap('teclas sem função')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'tabs', with_data=False)


def test_detail_navigation_and_search(demo, tui_factory):
    t = tui_factory()
    t.press('d', 'down', 'down', 'j').snap('Detalhe: cursor na 4ª linha')
    t.press('up', 'k').snap('Detalhe: volta 2')
    t.press('G').snap('Detalhe: G (último)')
    t.press('home').snap('Detalhe: Home (primeiro)')
    t.press('/').snap('busca aberta')
    t.type('tesouro').snap('busca "tesouro"')
    t.press('bs', 'bs', 'bs').snap('busca após backspace')
    t.press('enter').snap('busca confirmada')
    t.press('down').snap('navega dentro do filtro')
    t.press('/', 'esc').snap('Esc limpa a busca')
    t.press('/').type('nomad').press('enter').snap('busca por corretora')
    t.press('a', 'd').snap('trocar de aba limpa a busca')
    t.press('/').type('zzzz').press('enter').snap('busca sem resultado')
    t.press('enter').snap('Enter sem seleção não faz nada')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'detail_search', with_data=False)


def test_small_terminal(demo, tui_factory):
    t = tui_factory(cols=80, rows=24)
    t.snap('Sumário 80x24')
    t.press('d').snap('Detalhe 80x24')
    t.press('a').snap('Alocação 80x24')
    t.press('g').snap('Gráficos 80x24')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'small_terminal', with_data=False)


# ── Ações no ativo (Enter na aba Detalhe) ────────────────────────────────────

def test_asset_actions_and_save(demo, tui_factory):
    t = tui_factory()
    t.press('d', 'enter').snap('popup do 1º ativo (CDB Alfa)')
    t.press('u').snap('editar saldo: campo pré-preenchido')
    t.clear_field().type('24000,5').snap('novo saldo digitado')
    t.press('enter').snap('saldo atualizado')
    t.press('enter', 'a').fill('1000,37').snap('aporte R$ 1000,37')
    t.press('enter', 's').fill('500').snap('saque R$ 500')
    t.press('enter', 's').fill('99999999').snap('saque maior que saldo é ignorado')
    t.press('enter', 'a', 'esc').snap('aporte cancelado com Esc')
    t.press('enter', 'c').snap('popup cancelado')
    t.press('enter', 'esc').snap('popup fechado com Esc')
    # ativo em USD (SGOV): aporte e saque
    t.press('/').type('sgov').press('enter')
    t.press('enter').snap('popup ativo USD')
    t.press('a').fill('100').snap('aporte USD 100')
    t.press('enter', 's').fill('50').snap('saque USD 50')
    t.press('enter', 'u').fill('1000').snap('saldo USD 1000')
    # cripto: só atualizar quantidade
    t.press('/', 'esc', '/').type('bitcoin').press('enter')
    t.press('enter').snap('popup cripto (sem aporte/saque)')
    t.press('u').fill('0.01').snap('quantidade BTC 0.01')
    # excluir
    t.press('/', 'esc', '/').type('gold11').press('enter')
    t.press('enter', 'x').snap('confirmação de exclusão')
    t.press('n').snap('exclusão cancelada')
    t.press('enter', 'x', 's').snap('GOLD11 excluído (saldo sacado)')
    # salvar
    t.press('w').snap('popup salvar')
    t.press('c').snap('salvar cancelado')
    t.press('w', 's', until='✓ Salvo').snap('salvo (mensagem na barra)')
    t.press('s').snap('Sumário após salvar')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'asset_actions')


def test_provento(demo, tui_factory):
    # Provento pago na conta: só o lançamento; o saldo do FII não muda
    import json
    path = demo.root / 'data' / 'investments.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['flowsSince'] = '2026-10-01'          # lançamentos valendo desde o save de 01/10
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    t = tui_factory()
    t.press('d', '/').type('papl11').press('enter', 'enter').snap('popup do FII')
    t.press('p').snap('campo do provento')
    t.fill('72,5').snap('provento registrado')
    t.press('w', 's', until='✓ Salvo')
    t.press('s', 'G').snap('Sumário com coluna de proventos')
    t.press('q')
    assert t.wait_exit() == 0
    data = json.loads(path.read_text(encoding='utf-8'))
    [flow] = data['flows']
    assert flow['name'] == 'FII Papel Exemplo (PAPL11)' and flow['amount'] == -72.5
    assert flow['kind'] == 'provento'
    fii = next(i for i in data['investments'] if i['name'] == flow['name'])
    assert fii['balance'] == 7255.10
    finish(demo, t, 'provento', with_data=False)


def test_transfer(demo, tui_factory):
    # Transferir: sai de um ativo, entra em outro, sem lançamento (só a diferença, se houver)
    import json
    t = tui_factory()
    t.press('d', '/').type('liquidez').press('enter', 'enter').snap('popup com Transferir')
    t.press('t').snap('busca do destino')
    t.type('zzz').press('enter').snap('nada encontrado: busca de novo')
    t.clear_field().type('beta').press('enter').snap('lista de destinos')
    t.press('0').snap('valor que sai (padrão: saldo todo)')
    t.fill('5000').snap('valor que entra (padrão: o mesmo)')
    t.fill('5300').snap('entrou mais do que saiu')
    t.press('a').snap('transferido, diferença como aporte')
    # Resto do saldo para um ativo em dólar: valores padrão, convertidos pela cotação
    t.press('enter', 't').type('sgov').press('enter', '0').snap('sai o restante')
    t.press('enter').snap('entra em USD')
    t.press('enter').snap('origem zerada')
    t.press('x').snap('origem excluída')
    t.press('w', 's', until='✓ Salvo')
    t.press('q')
    assert t.wait_exit() == 0
    data = json.loads((demo.root / 'data' / 'investments.json').read_text(encoding='utf-8'))
    by_name = {i['name']: i for i in data['investments']}
    assert 'CDB Liquidez Diária Banco Exemplo' not in by_name
    assert by_name['LCA Banco Beta 95% CDI']['balance'] == round(16380.09 + 5300, 2)
    assert [(f['name'], f['amount']) for f in data['flows']] == [('LCA Banco Beta 95% CDI', 300.0)]
    finish(demo, t, 'transfer')


def test_liquidate_maturity(demo, tui_factory):
    # Vencimento: valor líquido, parte reinvestida, resto parado no caixa; o título sai
    import json
    t = tui_factory()
    t.press('d', '/').type('gama').press('enter', 'enter').snap('popup com Liquidar vencimento')
    t.press('v').snap('valor líquido (padrão: saldo)')
    t.fill('13700').snap('destino do dinheiro')
    t.press('t').type('beta').press('enter', '0').fill('8000').press('enter').snap('reinvestido: resta o resto')
    t.press('c').snap('resto no caixa: liquidado')
    # Outro título: tudo sacado para a conta
    t.press('/', 'esc', '/').type('2045').press('enter', 'enter', 'v', 'enter').snap('IPCA+ 2045: destino')
    t.press('s').snap('sacado: liquidado')
    t.press('w', 's', until='✓ Salvo')
    t.press('q')
    assert t.wait_exit() == 0
    data = json.loads((demo.root / 'data' / 'investments.json').read_text(encoding='utf-8'))
    by_name = {i['name']: i for i in data['investments']}
    assert 'CDB Banco Gama Pré 12,5%' not in by_name and 'Tesouro IPCA+ 2045' not in by_name
    assert by_name['LCA Banco Beta 95% CDI']['balance'] == round(16380.09 + 8000, 2)
    assert by_name['Caixa XP']['balance'] == 5700.0
    assert [(f['name'], f['amount']) for f in data['flows']] == [('Tesouro IPCA+ 2045', -10512.8)]
    finish(demo, t, 'liquidate')


def test_edit_asset(demo, tui_factory):
    # Editar: nome e corretora levam junto os lançamentos; saldo anterior segue o ativo
    import json
    t = tui_factory()
    t.press('d', '/').type('alfa').press('enter', 'enter', 'a').fill('100')   # lançamento antes
    t.press('enter', 'e').snap('campos do ativo')
    t.press('n').clear_field(40).type('CDB Banco Alfa 2028').press('enter').snap('nome trocado')
    t.press('n').clear_field(40).type('Tesouro Selic 2029').press('enter').snap('nome repetido na XP: erro no título')
    t.press('b', '1').snap('corretora trocada')
    t.press('v').fill('31/02/2028').snap('data inválida: erro no título')
    t.press('v').fill('15/06/2028')
    t.press('r', '0').fill('112,5')
    t.press('e', 'l', '3', 'a', '1').snap('vencimento, taxa, isenção, liquidez e categoria')
    t.press('c').snap('concluído')
    t.press('enter', 'u').fill('24000')                    # saldo novo depois da troca de nome
    t.press('w', 's', until='✓ Salvo')
    t.press('q')
    assert t.wait_exit() == 0
    data = json.loads((demo.root / 'data' / 'investments.json').read_text(encoding='utf-8'))
    a = next(i for i in data['investments'] if i['name'] == 'CDB Banco Alfa 2028')
    assert a['broker'] == 'Nubank' and a['maturity'] == '2028-06-15'
    assert a['rate'] == {'kind': 'PERCENT_CDI', 'value': 112.5}
    assert a['taxExempt'] is True and a['liquidity'] == 'AT_MATURITY'
    assert a['category'] == 'LCA'
    assert a['balance'] == 24000 and a['previousBalance'] == 23110.72   # saldo do início da sessão
    assert [(f['name'], f['broker']) for f in data['flows']] == [('CDB Banco Alfa 2028', 'Nubank')]
    finish(demo, t, 'edit_asset')


def test_flows_tab(demo, tui_factory):
    # Aba Lançamentos: lista por mês, do mais recente; Enter corrige o registro (saldos não mudam)
    import json
    def seed(d):
        d['flowsSince'] = '2026-09-01'
        d['flows'] = [
            {'date': '2026-08-20', 'name': 'Tesouro Selic 2029', 'broker': 'XP', 'amount': 500.0},
            {'date': '2026-09-15', 'name': 'FII Papel Exemplo (PAPL11)', 'broker': 'XP', 'amount': -72.5,
             'kind': 'provento'},
            {'date': '2026-10-02', 'name': 'SGOV', 'broker': 'Nomad', 'amount': 271.61, 'usd': 50.0},
            {'date': '2026-10-03', 'name': 'CDB Banco Alfa 110% CDI', 'broker': 'XP', 'amount': -1000.0},
        ]
    demo.edit(seed)
    # Saldos em reais (dólar e cripto mudam com as cotações ao abrir)
    brl = lambda d: {i['name']: i['balance'] for i in d['investments']
                     if 'investedUSD' not in i and i['category'] != 'Crypto'}
    before = brl(demo.read('investments.json'))
    t = tui_factory()
    t.press('l').snap('aba Lançamentos')
    t.press('enter').snap('popup do lançamento')
    t.press('v').fill('1200').snap('valor corrigido')
    t.press('enter', 't', 'a').snap('saque virou aporte')
    t.press('enter', 'a').type('beta').press('enter', '0').snap('ativo trocado')
    t.press('enter', 'd').fill('31/09/2026').snap('data inválida')
    t.press('down', 'enter', 'v').fill('60').snap('lançamento em USD: valor em dólar')
    t.press('down', 'down', 'enter', 'x', 's').snap('lançamento excluído')
    t.press('w', 's', until='✓ Salvo')
    t.press('q')
    assert t.wait_exit() == 0
    data = demo.read('investments.json')
    assert data['flows'] == [
        {'date': '2026-09-15', 'name': 'FII Papel Exemplo (PAPL11)', 'broker': 'XP', 'amount': -72.5,
         'kind': 'provento'},
        {'date': '2026-10-02', 'name': 'SGOV', 'broker': 'Nomad', 'amount': 325.93, 'usd': 60.0},
        {'date': '2026-10-03', 'name': 'LCA Banco Beta 95% CDI', 'broker': 'XP', 'amount': 1200.0},
    ]
    assert brl(data) == before
    finish(demo, t, 'flows_tab')


def test_open_warns_about_data_errors(demo, tui_factory):
    demo.edit(lambda d: d['investments'][0].update(maturity='31-02-2030'))
    t = tui_factory()
    t.wait_for('erro(s) nos dados')
    assert '✗ 1 erro(s) nos dados — rode: investsh check' in t.text()
    t.press('q')
    assert t.wait_exit() == 0


def test_update_all(demo, tui_factory):
    t = tui_factory()
    t.press('u').snap('1º ativo')
    t.press('enter').snap('Enter mantém → 2º ativo')
    t.clear_field().type('14000').press('enter').snap('2º alterado → 3º')
    t.clear_field().type('abc').snap('letras são ignoradas em campo numérico')
    t.press('enter')
    for _ in range(13):
        t.press('enter')
    t.snap('VT (USD)')
    t.fill('900').snap('Bitcoin: quantidade')
    t.fill('0.005').snap('Ethereum')
    t.press('esc').snap('Esc encerra a atualização')
    t.press('q').snap('popup de alterações não salvas')
    t.press('c').snap('cancelar mantém na TUI')
    t.press('q', 's')
    assert t.wait_exit() == 0
    finish(demo, t, 'update_all')


def test_quit_without_saving(demo, tui_factory):
    before = demo.data_snapshot()
    t = tui_factory()
    t.press('d', 'enter', 'u').fill('1')
    t.press('q').snap('popup alterações não salvas')
    t.press('q')
    assert t.wait_exit() == 0
    assert demo.data_snapshot() == before
    finish(demo, t, 'quit_no_save', with_data=False)


def test_new_assets(demo, tui_factory):
    t = tui_factory()
    t.press('n').snap('nome do ativo')
    t.type('CDB Novo').press('enter').snap('popup categoria')
    t.press('0').snap('popup tipo')
    t.press('0').snap('popup corretora')
    t.press('1').snap('vencimento')
    t.type('2027-01-01').press('enter').snap('popup indexador')
    t.press('0').snap('popup grupo de alocação')
    t.press('0').snap('popup objetivo')
    t.press('0').snap('custo base')
    t.fill('5000').snap('saldo atual')
    t.fill('5100').snap('origem do saldo inicial')
    t.press('a').snap('CDB Novo cadastrado (aporte)')

    # Nomad (USD), opções ≥ 10 escolhidas com setas
    t.press('n').type('ETF EUA').press('enter', '4', '4', '2', 'enter', '4')
    t.press(*(['down'] * 7), 'enter')          # RV_ETF_EXTERIOR
    t.press(*(['j'] * 9), 'enter')             # CRESCIMENTO_ACOES_EUA_EM_DOLAR
    t.snap('Nomad: custo base USD')
    t.fill('300').snap('Nomad: valor atual USD (padrão = custo)')
    t.fill('320').press('t').snap('ETF EUA cadastrado (veio de outro ativo)')

    # Cripto
    t.press('n').type('Solana').press('enter', '8', '4', '3', 'enter', '9')
    t.press(*(['down'] * 11), 'enter')          # RV_CRYPTO
    t.press(*(['down'] * 13), 'enter')          # ASSIMETRIA_E_EXPOSICAO_A_CRIPTO
    t.snap('cripto: quantidade')
    t.fill('2,5').snap('Solana cadastrada')

    # "Outro (digitar)" em indexador, grupo e objetivo
    t.press('n').type('Debênture X').press('enter', '0', '2', '1').type('2031-05-15').press('enter')
    t.press(*(['down'] * 10), 'enter').snap('indexador texto livre')
    t.type('IPCA+DEB').press('enter')
    t.press(*(['down'] * 14), 'enter').type('GRUPO_X').press('enter')
    t.press(*(['down'] * 23), 'enter').type('MEU_OBJETIVO').press('enter')
    t.fill('1000').fill('1000').press('a').snap('Debênture cadastrada')

    # cancelamentos
    t.press('n', 'enter').snap('nome vazio cancela')
    t.press('n').type('Cancelado').press('enter', 'esc').snap('Esc no popup cancela')
    t.press('d').snap('Detalhe com novos ativos')
    t.press('q', 's')
    assert t.wait_exit() == 0
    finish(demo, t, 'new_assets')


def test_params(demo, tui_factory):
    t = tui_factory()
    t.press('p').snap('FGTS')
    t.clear_field().type('20000').press('enter').snap('rendimento mensal')
    t.clear_field().type('0,9').press('enter')
    t.press('enter')                               # aporte: mantém
    t.clear_field().type('7').press('enter').snap('1ª meta de alocação')
    t.clear_field().type('50').press('enter')
    for _ in range(13):
        t.press('enter')
    t.snap('reserva mínima')
    t.clear_field().type('25000').press('enter', 'enter', 'enter').snap('parâmetros aplicados')
    t.press('p', 'esc').snap('Esc cancela parâmetros')
    t.press('q', 's')
    assert t.wait_exit() == 0
    finish(demo, t, 'params')


def test_reload_from_disk(demo, tui_factory):
    t = tui_factory()
    demo.edit(lambda d: d.update(fgts=99999.0))
    t.snap('antes do r')
    t.press('R').snap('após R: FGTS lido do disco')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'reload', with_data=False)


# ── Dados especiais ──────────────────────────────────────────────────────────

def test_edge_dataset(app, tui_factory):
    app.seed('edge')
    t = tui_factory()
    for key, label in (('s', 'Sumário'), ('r', 'Rentabilidade'), ('a', 'Alocação'), ('i', 'Indexador'), ('o', 'Objetivo'),
                       ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')):
        t.press(key).snap(label)
    t.press('w', 's', until='✓ Salvo').snap('salvo')
    t.press('q')
    assert t.wait_exit() == 0
    finish(app, t, 'edge')


def test_slow_central_bank_does_not_freeze(demo, tui_factory):
    # A API do Banco Central às vezes leva dezenas de segundos: a busca de CDI/IPCA
    # roda em segundo plano e as teclas continuam respondendo
    import time
    t = tui_factory(INVESTSH_TEST_BCB_DELAY='4')
    start = time.time()
    t.press('r', until='buscando no Banco Central')
    assert 'Desde 01/10/2025' in t.text()                  # carteira já calculada
    t.press('a', until='Categoria/Sub')
    t.press('r', until='buscando no Banco Central')
    assert time.time() - start < 3
    while 'buscando' in t.text():                           # redesenha sozinha ao terminar
        assert time.time() - start < 30, t.text()
        t.settle(quiet=0.3)
    assert 'indisponíve' not in t.text()
    assert '+13.94%' in t.text()                            # CDI do período preenchido
    t.press('q')
    assert t.wait_exit() == 0


def test_rates_unavailable(demo, tui_factory):
    t = tui_factory(INVESTSH_TEST_RATES='fail')
    t.snap('Sumário sem cotações')
    t.press('d').snap('Detalhe sem cotações')
    t.press('r').snap('Rentabilidade sem conexão com o Banco Central')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'rates_fail', with_data=False)


def test_first_run_then_tui(app, tui_factory):
    t = tui_factory()
    # Só texto: o caminho absoluto impresso tem tamanho diferente em macOS (/private/tmp) e Linux
    t.snap('pergunta de primeira execução', styles=False)
    t.press('2', 'enter')
    t.READY = (t.TAB_BAR,)
    t.wait_ready()
    t.snap('TUI com dados de exemplo')
    t.press('q')
    assert t.wait_exit() == 0
    finish(app, t, 'first_run', with_data=False)


def test_empty_portfolio(app, tui_factory):
    # Sem matplotlib: com ele, o resultado depende da versão (bug da imagem com carteira vazia)
    t = tui_factory(INVESTSH_TEST_NO_MPL='1')
    t.press('1', 'enter')
    t.READY = (t.TAB_BAR,)
    t.wait_ready()
    for key, label in (('s', 'Sumário'), ('r', 'Rentabilidade'), ('a', 'Alocação'), ('i', 'Indexador'), ('o', 'Objetivo'),
                       ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')):
        t.press(key).snap(label)
    t.press('w', 's', until='✓ Salvo').snap('salvo')
    t.press('q')
    assert t.wait_exit() == 0
    finish(app, t, 'empty')


def test_save_auto_git_status(demo, tmp_path, tui_factory):
    remote = tmp_path / 'remote.git'
    run = lambda *a, cwd=demo.root: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
    run('init', '-q', '--bare', str(remote), cwd=tmp_path)
    run('init', '-q', '-b', 'main')
    run('-c', 'user.email=t@e.com', '-c', 'user.name=T', 'commit', '-q', '--allow-empty', '-m', 'seed')
    run('remote', 'add', 'origin', str(remote))
    run('push', '-q', '-u', 'origin', 'main')
    run('config', 'user.email', 't@e.com')
    run('config', 'user.name', 'T')

    t = tui_factory(FINANCES_AUTO_GIT='1')
    t.press('w', 's', until='push ok').snap('salvo com push')
    t.press('q')
    assert t.wait_exit() == 0
    log = subprocess.run(['git', 'log', '-1', '--format=%s', 'main'], cwd=remote, capture_output=True, text=True)
    assert log.stdout == 'update 2026-10\n'
    finish(demo, t, 'auto_git', with_data=False)


def test_save_auto_git_failure_status(demo, tui_factory):
    t = tui_factory(FINANCES_AUTO_GIT='1')   # fora de repositório git
    t.press('w', 's', until='git falhou').snap('salvo, git falhou')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'auto_git_fail', with_data=False)


def test_field_editing_and_popup_keys(demo, tui_factory):
    t = tui_factory()
    t.press('d', 'enter', 'u').snap('campo com valor atual')
    t.press('left', 'left', 'bs').snap('← ← e apaga no meio')
    t.press('right', '9').snap('→ e insere')
    t.press('enter').snap('valor editado salvo no ativo')
    t.press('enter', 'u').fill('1,2,3').snap('número inválido volta ao valor padrão')
    t.press('esc')
    t.press('enter', 'down', 'down', 'up', 'k').snap('popup: ↓ ↓ ↑ k')
    t.press('z').snap('popup: tecla sem opção é ignorada')
    t.press('enter').snap('Enter escolhe a opção destacada')
    t.press('esc')
    t.press('q', 'q')
    assert t.wait_exit() == 0
    finish(demo, t, 'field_editing', with_data=False)


def test_detail_scroll_follows_cursor(demo, tui_factory):
    t = tui_factory(cols=80, rows=24)
    t.press('d', *(['down'] * 25)).snap('cursor desceu além da tela')
    t.press(*(['up'] * 22)).snap('cursor subiu além da tela')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'detail_scroll', with_data=False)


def test_save_twice_same_day(demo, tui_factory):
    t = tui_factory()
    t.press('w', 's', until='✓ Salvo').snap('1º save')
    t.press('d', 'enter', 'u').fill('1').press('w', 's', until='✓ Salvo').snap('2º save')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'save_twice')


def test_save_without_matplotlib(demo, tui_factory):
    t = tui_factory(INVESTSH_TEST_NO_MPL='1')
    t.press('w', 's', until='✓ Salvo').snap('salvo sem matplotlib')
    t.press('q')
    assert t.wait_exit() == 0
    assert not (demo.root / 'assets' / 'status.png').exists()
    finish(demo, t, 'save_no_matplotlib')


def test_zero_balances(demo, tui_factory):
    demo.edit(lambda d: [i.update(balance=0.0, previousBalance=0.0) for i in d['investments']])
    t = tui_factory(INVESTSH_TEST_RATES='fail')
    for key, label in (('s', 'Sumário'), ('r', 'Rentabilidade'), ('a', 'Alocação'), ('i', 'Indexador'), ('o', 'Objetivo'),
                       ('d', 'Detalhe'), ('b', 'Brokers'), ('g', 'Gráficos')):
        t.press(key).snap(label)
    t.press('w', 's', until='✓ Salvo').snap('salvo')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'zero_balances')


def test_accented_input(demo, tui_factory):
    t = tui_factory()
    t.press('d', '/').type('previdência').snap('busca com acento')
    t.press('bs').snap('backspace apaga o caractere inteiro')
    t.press('a', 'enter').snap('busca confirmada')
    t.press('n').type('Ação Ê ç').snap('nome com acentos')
    t.press('left', 'bs').type('Ç').snap('edição no meio do texto acentuado')
    t.press('esc')
    t.press('q')
    assert t.wait_exit() == 0
    finish(demo, t, 'accented_input', with_data=False)


def test_save_keeps_stderr_off_screen(demo, tui_factory):
    t = tui_factory(INVESTSH_TEST_STDERR_NOISE='1')
    t.press('w', 's', until='✓ Salvo')
    assert 'RUIDO' not in t.text()
    t.press('q')
    assert t.wait_exit() == 0


def test_startup_warns_about_maturities(app, tui_factory):
    app.seed('edge')   # um ativo vence em 26 dias e outro já venceu (com saldo)
    t = tui_factory()
    assert '⚠ 2 ativo(s) vencem em até 30 dias ou já venceram (veja o Sumário)' in t.text()
    t.press('q')
    assert t.wait_exit() == 0


def test_no_startup_warning_without_urgent_maturities(demo, tui_factory):
    t = tui_factory()
    assert '⚠' not in t.text()
    t.press('q')
    assert t.wait_exit() == 0
