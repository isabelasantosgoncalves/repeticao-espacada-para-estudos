"""Testes da lógica de repetição espaçada. Rode com: python -m unittest"""

import unittest
from datetime import date, timedelta

import logica as L

HOJE = date(2026, 3, 10)  # uma terça-feira


def ci(*args, **kwargs):
    """calcular_intervalo sem a fase de aprendizado, para testar tabela e bônus isolados."""
    kwargs.setdefault("tetos", ())
    return L.calcular_intervalo(*args, **kwargs)


def estado(aid, dom_ef, prio, proxima=HOJE):
    """Atalho para montar um EstadoAssunto nos testes de seleção."""
    return L.EstadoAssunto(
        assunto_id=aid, n_sessoes=1, ultima_data=proxima - timedelta(days=2),
        ultimo_pct=dom_ef, dominio=dom_ef, intervalo=2, sequencia_boa=0,
        proxima_revisao=proxima, atraso=0, dominio_efetivo=dom_ef,
        prioridade=prio, questoes=10,
    )


class TestTabela(unittest.TestCase):
    def test_faixas(self):
        self.assertEqual(L.faixa_da_tabela(0.49), (2, 20))
        self.assertEqual(L.faixa_da_tabela(0.50), (4, 15))
        self.assertEqual(L.faixa_da_tabela(0.69), (4, 15))
        self.assertEqual(L.faixa_da_tabela(0.70), (7, 10))
        self.assertEqual(L.faixa_da_tabela(0.84), (7, 10))
        self.assertEqual(L.faixa_da_tabela(0.85), (15, 6))
        self.assertEqual(L.faixa_da_tabela(0.94), (15, 6))
        self.assertEqual(L.faixa_da_tabela(0.95), (30, 4))
        self.assertEqual(L.faixa_da_tabela(1.0), (30, 4))

    def test_fracao_exata_no_limite(self):
        # 17/20 = 85% e 19/20 = 95% precisam cair na faixa de cima
        self.assertEqual(L.faixa_da_tabela(17 / 20), (15, 6))
        self.assertEqual(L.faixa_da_tabela(19 / 20), (30, 4))
        self.assertEqual(L.faixa_da_tabela(7 / 10), (7, 10))

    def test_percentual_valida(self):
        self.assertEqual(L.percentual(3, 4), 0.75)
        with self.assertRaises(ValueError):
            L.percentual(5, 4)
        with self.assertRaises(ValueError):
            L.percentual(0, 0)

    def test_peso_por_tamanho(self):
        self.assertAlmostEqual(L.peso_por_tamanho(2), 0.2)
        self.assertEqual(L.peso_por_tamanho(10), 1.0)
        self.assertEqual(L.peso_por_tamanho(40), 1.0)
        self.assertEqual(L.peso_por_tamanho(None), 1.0)

    def test_questoes(self):
        self.assertEqual(L.questoes_sugeridas(0.3), 20)
        self.assertEqual(L.questoes_sugeridas(0.97), 4)
        self.assertEqual(L.questoes_sugeridas(0.3, numero_fixo=12), 12)


class TestIntervalo(unittest.TestCase):
    def test_uma_sessao_usa_tabela(self):
        self.assertEqual(ci([0.4]), (2, 0))
        self.assertEqual(ci([0.75]), (7, 0))
        self.assertEqual(ci([0.9]), (15, 1))

    def test_bonus_dobra(self):
        self.assertEqual(ci([0.9, 0.9])[0], 30)
        self.assertEqual(ci([0.9, 0.9, 0.9])[0], 60)
        self.assertEqual(ci([0.9, 0.9, 0.9, 0.9])[0], 120)

    def test_bonus_nunca_abaixo_da_tabela(self):
        # 90% (15 dias) seguido de 100%: dobra para 30, igual à tabela
        self.assertEqual(ci([0.9, 1.0])[0], 30)
        # 100% e 100%: 30 -> 60
        self.assertEqual(ci([1.0, 1.0])[0], 60)

    def test_bonus_completo_dobra(self):
        # 3ª sessão com 20 questões (sugeridas: 6) -> dobra 30 -> 60
        self.assertEqual(ci([0.9, 0.9, 0.9], [20, 20, 20])[0], 60)

    def test_bonus_sessao_pequena_cresce_pouco(self):
        # 1 de 1 com 6 sugeridas: 30 x (1 + 1/6) = 35, não 60
        self.assertEqual(ci([0.9, 0.9, 1.0], [20, 20, 1])[0], 35)

    def test_fator_bonus(self):
        self.assertEqual(L.fator_bonus(4, 4), 2.0)
        self.assertEqual(L.fator_bonus(10, 4), 2.0)
        self.assertAlmostEqual(L.fator_bonus(1, 4), 1.25)
        self.assertEqual(L.fator_bonus(None, 6), 2.0)

    def test_bonus_tem_teto(self):
        self.assertEqual(ci([1.0] * 10)[0], L.INTERVALO_MAXIMO)

    def test_queda_usa_tabela_pelo_dominio(self):
        # domínio = 0,5·60 + 0,3·90 + 0,2·90 = 75% -> 7 dias, sem bônus
        self.assertEqual(ci([0.9, 0.9, 0.9, 0.6]), (7, 0))
        # domínio = 0,5·30 + 0,3·90 + 0,2·90 = 60% -> 4 dias
        self.assertEqual(ci([0.9, 0.9, 0.3]), (4, 0))
        # sessão de 80% quebra a sequência; domínio 85% -> 15 dias da tabela
        self.assertEqual(ci([0.9, 0.9, 0.8]), (15, 0))

    def test_quedas_seguidas_chegam_ao_fundo_da_tabela(self):
        self.assertEqual(ci([0.3, 0.3, 0.3])[0], 2)

    def test_sequencia_recomeca(self):
        # sequência quebrada: domínio 81% -> 7 dias, sequência 1
        self.assertEqual(ci([0.9, 0.6, 0.9]), (7, 1))


class TestSessoesPequenas(unittest.TestCase):
    """Errar 1 de 2 questões não pode valer o mesmo que errar 10 de 20."""

    def test_sessao_pequena_ruim_mexe_pouco(self):
        pcts, totais = [0.9, 0.9, 0.5], [20, 20, 2]
        # pesos: 0,5·0,2 = 0,1 | 0,3 | 0,2  -> (0,05 + 0,27 + 0,18) / 0,6 = 83,3%
        self.assertAlmostEqual(L.dominio(pcts, totais), 0.5 / 0.6)
        self.assertEqual(ci(pcts, totais), (7, 0))

    def test_sessao_grande_ruim_mexe_mais(self):
        pcts, totais = [0.9, 0.9, 0.5], [20, 20, 20]
        self.assertAlmostEqual(L.dominio(pcts, totais), 0.70)
        self.assertEqual(ci(pcts, totais)[0], 7)
        pcts, totais = [0.9, 0.9, 0.3], [20, 20, 20]
        self.assertEqual(ci(pcts, totais)[0], 4)

    def test_pequenas_ruins_seguidas_descem_aos_poucos(self):
        base, tb = [0.9, 0.9], [20, 20]
        d1 = L.dominio(base + [0.5], tb + [2])
        d2 = L.dominio(base + [0.5, 0.5], tb + [2, 2])
        d3 = L.dominio(base + [0.5, 0.5, 0.5], tb + [2, 2, 2])
        self.assertGreater(d1, d2)
        self.assertGreater(d2, d3)
        self.assertAlmostEqual(d3, 0.5)   # só sessões pequenas na janela: pesam igual
        intervalos = [ci(base + [0.5] * k, tb + [2] * k)[0] for k in (1, 2, 3)]
        self.assertEqual(intervalos, [7, 7, 4])

    def test_estado_usa_totais(self):
        d0 = HOJE - timedelta(days=40)
        sessoes = [(d0, 18, 20), (d0 + timedelta(days=15), 18, 20), (HOJE - timedelta(days=1), 1, 2)]
        e = L.analisar_assunto(1, sessoes, HOJE)
        self.assertEqual(e.intervalo, 7)
        self.assertEqual(e.questoes, 10)
        self.assertAlmostEqual(e.ultimo_pct, 0.5)


class TestDominio(unittest.TestCase):
    def test_tres_sessoes(self):
        # mais recente 1.0 (50%), anterior 0.5 (30%), antepenúltima 0.0 (20%)
        self.assertAlmostEqual(L.dominio([0.0, 0.5, 1.0]), 0.65)

    def test_usa_so_as_ultimas_tres(self):
        self.assertAlmostEqual(L.dominio([1.0, 0.0, 0.5, 1.0]), 0.65)

    def test_normaliza_com_menos_sessoes(self):
        self.assertAlmostEqual(L.dominio([0.8]), 0.8)
        # pesos 0.5 e 0.3 normalizados -> 0.625 e 0.375
        self.assertAlmostEqual(L.dominio([0.4, 0.8]), 0.8 * 0.625 + 0.4 * 0.375)

    def test_sem_sessoes(self):
        self.assertEqual(L.dominio([]), 0.0)


class TestEsquecimento(unittest.TestCase):
    def test_semana_incompleta_nao_perde(self):
        self.assertAlmostEqual(L.dominio_efetivo(0.8, 6), 0.8)

    def test_perde_por_semana_completa(self):
        self.assertAlmostEqual(L.dominio_efetivo(0.8, 7), 0.75)
        self.assertAlmostEqual(L.dominio_efetivo(0.8, 20), 0.70)

    def test_minimo_zero(self):
        self.assertEqual(L.dominio_efetivo(0.1, 70), 0.0)

    def test_atraso(self):
        self.assertEqual(L.dias_de_atraso(HOJE, HOJE), 0)
        self.assertEqual(L.dias_de_atraso(HOJE + timedelta(days=3), HOJE), 0)
        self.assertEqual(L.dias_de_atraso(HOJE - timedelta(days=4), HOJE), 4)


class TestPrioridade(unittest.TestCase):
    def test_formula(self):
        self.assertAlmostEqual(L.prioridade(0.7, 0), 0.3)
        self.assertAlmostEqual(L.prioridade(0.7, 5), 0.8)

    def test_atraso_pesa_mais_que_dominio_baixo(self):
        # 90% de domínio com 10 dias de atraso passa à frente de 40% em dia
        self.assertGreater(L.prioridade(0.9, 10), L.prioridade(0.4, 0))


class TestAnalisarAssunto(unittest.TestCase):
    def test_sem_sessoes(self):
        self.assertIsNone(L.analisar_assunto(1, [], HOJE))

    def test_estado_completo(self):
        d0 = HOJE - timedelta(days=15)
        sessoes = [(d0, 9, 10), (d0 + timedelta(days=5), 18, 20)]  # 90%, 90%
        e = L.analisar_assunto(7, sessoes, HOJE)
        # 2ª sessão ainda na fase de aprendizado: bônus daria 30, o teto é 15
        self.assertEqual(e.intervalo, 15)
        self.assertEqual(e.proxima_revisao, d0 + timedelta(days=20))
        self.assertEqual(e.atraso, 0)
        self.assertAlmostEqual(e.dominio, 0.9)
        self.assertEqual(e.questoes, 6)

    def test_atrasado_perde_dominio(self):
        d0 = HOJE - timedelta(days=16)  # 50% -> revisão em 4 dias -> 12 de atraso
        e = L.analisar_assunto(1, [(d0, 5, 10)], HOJE)
        self.assertEqual(e.atraso, 12)
        self.assertAlmostEqual(e.dominio_efetivo, 0.45)
        self.assertAlmostEqual(e.prioridade, 0.55 + 1.2)

    def test_ordem_de_entrada_nao_importa(self):
        a, b = HOJE - timedelta(days=10), HOJE - timedelta(days=3)
        e1 = L.analisar_assunto(1, [(a, 2, 10), (b, 10, 10)], HOJE)
        e2 = L.analisar_assunto(1, [(b, 10, 10), (a, 2, 10)], HOJE)
        self.assertEqual(e1.ultimo_pct, e2.ultimo_pct)


class TestAgenda(unittest.TestCase):
    def test_proximo_dia_fixo(self):
        # HOJE é terça (1); próximo domingo (6) = 15/03
        self.assertEqual(L.proximo_dia_fixo(HOJE, [6]), date(2026, 3, 15))
        # se hoje é dia fixo, o próximo é na semana seguinte
        self.assertEqual(L.proximo_dia_fixo(HOJE, [1]), date(2026, 3, 17))
        self.assertEqual(L.proximo_dia_fixo(HOJE, [1, 3]), date(2026, 3, 12))
        self.assertIsNone(L.proximo_dia_fixo(HOJE, []))

    def test_tipo_de_revisao(self):
        self.assertEqual(L.tipo_de_revisao("fixa", [1], HOJE), "grande")
        self.assertIsNone(L.tipo_de_revisao("fixa", [6], HOJE))
        self.assertEqual(L.tipo_de_revisao("diaria", [], HOJE), "diaria")
        self.assertEqual(L.tipo_de_revisao("ambos", [1], HOJE), "grande")
        self.assertEqual(L.tipo_de_revisao("ambos", [6], HOJE), "diaria")
        self.assertEqual(L.tipo_de_revisao("completa", [], HOJE), "completa")
        self.assertEqual(L.tipo_de_revisao("completa", [1], HOJE), "completa")


class TestSelecaoDiaria(unittest.TestCase):
    def setUp(self):
        self.estados = [
            estado(1, 0.90, 0.10),
            estado(2, 0.30, 0.70),
            estado(3, 0.50, 0.50),
            estado(4, 0.70, 0.30),
        ]

    def ids(self, lista):
        return sorted(e.assunto_id for e in lista)

    def test_ontem_mais_menor_dominio(self):
        sel = L.selecionar_revisao_diaria(self.estados, [1], 2)
        self.assertEqual(self.ids(sel), [1, 2])

    def test_ontem_e_o_menor_dominio_pega_o_proximo(self):
        sel = L.selecionar_revisao_diaria(self.estados, [2], 2)
        self.assertEqual(self.ids(sel), [2, 3])

    def test_sem_assunto_ontem(self):
        sel = L.selecionar_revisao_diaria(self.estados, [], 3)
        self.assertEqual(self.ids(sel), [2, 3, 4])

    def test_muitos_de_ontem_pega_os_de_menor_dominio(self):
        sel = L.selecionar_revisao_diaria(self.estados, [1, 4, 3], 2)
        self.assertEqual(self.ids(sel), [3, 4])   # 50% e 70%, não o de 90%

    def test_n_maior_que_disponivel(self):
        self.assertEqual(len(L.selecionar_revisao_diaria(self.estados, [1], 10)), 4)

    def test_ontem_desconhecido_e_ignorado(self):
        sel = L.selecionar_revisao_diaria(self.estados, [99], 1)
        self.assertEqual(self.ids(sel), [2])

    def test_resultado_ordenado_por_prioridade(self):
        sel = L.selecionar_revisao_diaria(self.estados, [1], 3)
        prios = [e.prioridade for e in sel]
        self.assertEqual(prios, sorted(prios, reverse=True))


class TestSelecaoGrande(unittest.TestCase):
    def test_vencidos_e_que_vencem_ate_o_proximo_fixo(self):
        prox = HOJE + timedelta(days=7)
        estados = [
            estado(1, 0.5, 2.0, proxima=HOJE - timedelta(days=5)),   # vencido
            estado(2, 0.8, 0.2, proxima=HOJE),                       # vence hoje
            estado(3, 0.6, 0.4, proxima=HOJE + timedelta(days=6)),   # antes do próximo fixo
            estado(4, 0.9, 0.1, proxima=prox),                       # fica para o próximo
            estado(5, 0.9, 0.1, proxima=HOJE + timedelta(days=20)),
        ]
        sel = L.selecionar_revisao_grande(estados, HOJE, prox)
        self.assertEqual([e.assunto_id for e in sel], [1, 3, 2])


class TestFaseDeAprendizado(unittest.TestCase):
    def test_assunto_novo_nao_vai_direto_para_30_dias(self):
        self.assertEqual(L.calcular_intervalo([1.0], [5])[0], 7)
        self.assertEqual(L.calcular_intervalo([1.0, 1.0], [5, 5])[0], 15)
        self.assertEqual(L.calcular_intervalo([1.0, 1.0, 1.0], [5, 5, 5])[0], 30)
        self.assertEqual(L.calcular_intervalo([1.0] * 4, [5] * 4)[0], 60)

    def test_teto_nao_aumenta_intervalo_curto(self):
        # errou muito: a tabela (2 dias) já é menor que o teto
        self.assertEqual(L.calcular_intervalo([0.3], [10])[0], 2)

    def test_estado_marca_fase(self):
        d = HOJE - timedelta(days=1)
        self.assertTrue(L.analisar_assunto(1, [(d, 5, 5)], HOJE).em_aprendizado)
        tres = [(d - timedelta(days=20), 5, 5), (d - timedelta(days=10), 5, 5), (d, 5, 5)]
        self.assertFalse(L.analisar_assunto(1, tres, HOJE).em_aprendizado)


class TestEscolhaDaFase(unittest.TestCase):
    def test_opcoes(self):
        seq = lambda nome, n: L.calcular_intervalo([1.0] * n, [10] * n, tetos=L.tetos_da_fase(nome))[0]
        self.assertEqual([seq("padrao", n) for n in (1, 2, 3, 4)], [7, 15, 30, 60])
        self.assertEqual([seq("cautelosa", n) for n in (1, 2, 3, 4, 5)], [2, 4, 8, 15, 30])
        self.assertEqual([seq("degraus", n) for n in (1, 2, 3, 4)], [3, 7, 15, 30])
        self.assertEqual([seq("solta", n) for n in (1, 2, 3)], [10, 20, 40])
        # o rótulo de cada opção mostra exatamente essa sequência
        self.assertEqual([seq("cautelosa", n) for n in (1, 2, 3, 4, 5, 6)], [2, 4, 8, 15, 30, 60])

    def test_desconhecida_usa_padrao(self):
        self.assertEqual(L.tetos_da_fase(None), L.TETOS_APRENDIZADO)
        self.assertEqual(L.tetos_da_fase("xyz"), L.TETOS_APRENDIZADO)

    def test_fase_de_tres_degraus_no_estado(self):
        d = HOJE - timedelta(days=1)
        sess = [(d - timedelta(days=10), 5, 5), (d - timedelta(days=5), 5, 5), (d, 5, 5)]
        e = L.analisar_assunto(1, sess, HOJE, tetos=L.tetos_da_fase("degraus"))
        self.assertTrue(e.em_aprendizado)
        self.assertEqual(e.fase_total, 3)


class TestTetoDoUsuario(unittest.TestCase):
    def test_sugestao_pelas_respostas(self):
        self.assertEqual(L.sugerir_teto("leve", "padrao"), 60)
        self.assertEqual(L.sugerir_teto("moderado", "padrao"), 45)
        self.assertEqual(L.sugerir_teto("intenso", "padrao"), 30)
        self.assertEqual(L.sugerir_teto("leve", "cautelosa"), 45)
        self.assertEqual(L.sugerir_teto("moderado", "solta"), 60)
        self.assertEqual(L.sugerir_teto("intenso", "cautelosa"), 21)   # nunca abaixo de 21

    def test_teto_limita_o_intervalo_final(self):
        sess = [1.0] * 6
        self.assertGreater(L.calcular_intervalo(sess, [10] * 6)[0], 45)
        self.assertEqual(L.calcular_intervalo(sess, [10] * 6, teto=45)[0], 45)
        self.assertEqual(L.calcular_intervalo(sess, [10] * 6, teto=30, fator=0.5)[0], 30)

    def test_livre_dobra_ate_um_ano(self):
        seq = [L.calcular_intervalo([1.0] * n, [10] * n, teto=L.TETO_LIVRE)[0] for n in range(3, 8)]
        self.assertEqual(seq, [30, 60, 120, 240, 365])

    def test_teto_nao_mexe_em_intervalo_curto(self):
        self.assertEqual(L.calcular_intervalo([0.3], [10], teto=30)[0], 2)


class TestRitmo(unittest.TestCase):
    def test_fatores(self):
        self.assertEqual(L.fator_do_ritmo("leve"), 1.0)
        self.assertEqual(L.fator_do_ritmo("moderado"), 0.75)
        self.assertEqual(L.fator_do_ritmo("intenso"), 0.5)
        self.assertEqual(L.fator_do_ritmo(None), 1.0)

    def test_tabela_em_cada_ritmo(self):
        tabela = [2, 4, 7, 15, 30]
        self.assertEqual([L.aplicar_ritmo(d, 0.75) for d in tabela], [2, 3, 5, 11, 22])
        self.assertEqual([L.aplicar_ritmo(d, 0.5) for d in tabela], [1, 2, 4, 8, 15])

    def test_ritmo_vale_para_o_bonus(self):
        base = L.calcular_intervalo([1.0] * 4, [5] * 4)[0]          # 60
        self.assertEqual(L.calcular_intervalo([1.0] * 4, [5] * 4, fator=0.5)[0], base // 2)

    def test_estado_usa_fator(self):
        d = HOJE - timedelta(days=1)
        e = L.analisar_assunto(1, [(d, 5, 5)], HOJE, fator=0.5)
        self.assertEqual(e.intervalo, 4)          # teto 7 x 0,5



class TestGrupo(unittest.TestCase):
    def test_media_simples_dos_subassuntos(self):
        self.assertAlmostEqual(L.dominio_do_grupo([0.9, 0.3]), 0.6)

    def test_sem_subassuntos_estudados(self):
        self.assertIsNone(L.dominio_do_grupo([]))


class TestSelecaoCompleta(unittest.TestCase):
    def test_tudo_que_vence_ou_atrasou_sem_limite(self):
        estados = [
            estado(1, 0.5, 2.0, proxima=HOJE - timedelta(days=5)),   # atrasado
            estado(2, 0.8, 0.2, proxima=HOJE),                       # vence hoje
            estado(3, 0.6, 0.4, proxima=HOJE + timedelta(days=1)),   # amanhã: fica de fora
            estado(4, 0.3, 0.7, proxima=HOJE),                       # vence hoje
        ]
        sel = L.selecionar_revisao_completa(estados, HOJE)
        self.assertEqual([e.assunto_id for e in sel], [1, 4, 2])


class TestDiasDaSecao(unittest.TestCase):
    # HOJE (10/03/2026) é terça (1). Seção estudada seg/qua/sex = [0, 2, 4].
    SQS = [0, 2, 4]

    def test_estuda_no_dia(self):
        self.assertTrue(L.estuda_no_dia(HOJE, []))
        self.assertFalse(L.estuda_no_dia(HOJE, self.SQS))
        self.assertTrue(L.estuda_no_dia(HOJE + timedelta(days=1), self.SQS))

    def test_revisao_passa_para_o_proximo_dia_de_estudo(self):
        self.assertEqual(L.ajustar_para_dia_de_estudo(HOJE, self.SQS), HOJE + timedelta(days=1))
        self.assertEqual(L.ajustar_para_dia_de_estudo(HOJE, []), HOJE)

    def test_dia_sem_estudo_nao_conta_como_atraso(self):
        # 50% há 4 dias -> revisão "hoje" (terça); com seg/qua/sex vai para quarta
        d = HOJE - timedelta(days=4)
        livre = L.analisar_assunto(1, [(d, 5, 10)], HOJE)
        secao = L.analisar_assunto(1, [(d, 5, 10)], HOJE + timedelta(days=1), dias_estudo=self.SQS)
        self.assertEqual(livre.proxima_revisao, HOJE)
        self.assertEqual(secao.proxima_revisao, HOJE + timedelta(days=1))
        self.assertEqual(secao.atraso, 0)


class TestAdiantar(unittest.TestCase):
    def test_pega_as_mais_proximas(self):
        estados = [
            estado(1, 0.9, 0.1, proxima=HOJE + timedelta(days=9)),
            estado(2, 0.6, 0.4, proxima=HOJE + timedelta(days=2)),
            estado(3, 0.8, 0.2, proxima=HOJE + timedelta(days=2)),
            estado(4, 0.5, 0.5, proxima=HOJE + timedelta(days=5)),
        ]
        self.assertEqual([e.assunto_id for e in L.selecionar_adiantadas(estados, HOJE, 1)], [2])
        self.assertEqual([e.assunto_id for e in L.selecionar_adiantadas(estados, HOJE, 3)], [2, 3, 4])
        self.assertEqual(L.selecionar_adiantadas(estados, HOJE, 0), [])


class TestMapa(unittest.TestCase):
    def test_classificacao(self):
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.9, 0.1, HOJE), HOJE), "agora")
        futuro = HOJE + timedelta(days=3)
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.9, 0.1, futuro), HOJE), "dominado")
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.6, 0.4, futuro), HOJE), "esperar")


if __name__ == "__main__":
    unittest.main()
