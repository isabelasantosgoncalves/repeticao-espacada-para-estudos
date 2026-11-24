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
        self.assertEqual(L.faixa_da_tabela(0.49), (3, 20))
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
        self.assertEqual(ci([0.4]), (3, 0))
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
        self.assertEqual(ci([0.3, 0.3, 0.3])[0], 3)

    def test_sequencia_recomeca(self):
        # sequência quebrada: domínio 81% -> 7 dias, sequência 1
        self.assertEqual(ci([0.9, 0.6, 0.9]), (7, 1))


class TestSessoesPequenas(unittest.TestCase):
    """Errar 1 de 2 questões não pode valer o mesmo que errar 10 de 20."""

    def test_sessao_pequena_ruim_mexe_pouco(self):
        pcts, totais = [0.9, 0.9, 0.5], [20, 20, 2]
        # pesos: 0,5·0,2 = 0,1 | 0,3 | 0,2  -> (0,05 + 0,27 + 0,18) / 0,6 = 83,3%
        self.assertAlmostEqual(L.dominio(pcts, totais), 0.5 / 0.6)
        # a tabela pediria 7 dias, mas 2 de 6 questões sugeridas andam só 1/3: 30 -> 22
        self.assertEqual(ci(pcts, totais), (22, 0))

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
        self.assertEqual(intervalos, [22, 19, 16])   # desce aos poucos

    def test_estado_usa_totais(self):
        d0 = HOJE - timedelta(days=40)
        sessoes = [(d0, 18, 20), (d0 + timedelta(days=15), 18, 20), (HOJE - timedelta(days=1), 1, 2)]
        e = L.analisar_assunto(1, sessoes, HOJE)
        self.assertEqual(e.intervalo, 12)         # 15 -> anda 1/3 do caminho até 7 (2 de 6 sugeridas)
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
    """Revisão do dia: só o que venceu, até n por seção, pelos que mais precisam."""

    def setUp(self):
        antes = HOJE - timedelta(days=1)
        depois = HOJE + timedelta(days=2)
        self.estados = [
            estado(1, 0.90, 0.10, proxima=antes),
            estado(2, 0.30, 0.70, proxima=HOJE),
            estado(3, 0.50, 0.50, proxima=antes),
            estado(4, 0.20, 0.80, proxima=depois),   # ainda não venceu
            estado(5, 0.60, 0.40, proxima=HOJE),
        ]
        self.secao = {1: "Math", 2: "Math", 3: "Math", 4: "Math", 5: "English"}

    def ids(self, lista):
        return [e.assunto_id for e in lista]

    def test_so_o_que_venceu(self):
        sel = L.selecionar_revisao_diaria(self.estados, HOJE, 10, self.secao)
        self.assertNotIn(4, self.ids(sel))
        self.assertEqual(sorted(self.ids(sel)), [1, 2, 3, 5])

    def test_limite_por_secao_pelos_que_mais_precisam(self):
        sel = L.selecionar_revisao_diaria(self.estados, HOJE, 2, self.secao)
        self.assertEqual(self.ids(sel), [2, 3, 5])   # Math: 2 e 3 (prioridade maior); English: 5

    def test_sem_secoes_o_limite_vale_para_tudo(self):
        self.assertEqual(len(L.selecionar_revisao_diaria(self.estados, HOJE, 2)), 2)

    def test_nada_venceu(self):
        futuros = [estado(9, 0.2, 0.8, proxima=HOJE + timedelta(days=3))]
        self.assertEqual(L.selecionar_revisao_diaria(futuros, HOJE, 3), [])


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
        self.assertEqual(L.calcular_intervalo([1.0], [10])[0], 7)
        self.assertEqual(L.calcular_intervalo([1.0, 1.0], [10, 5])[0], 15)
        self.assertEqual(L.calcular_intervalo([1.0, 1.0, 1.0], [10, 5, 5])[0], 30)
        self.assertEqual(L.calcular_intervalo([1.0] * 4, [10] + [5] * 3)[0], 60)

    def test_volta_antes_se_nao_foi_bem(self):
        # Equilíbrio (7, 15): bom 7, médio 4 (metade, para cima), mal 1
        self.assertEqual(L.calcular_intervalo([1.0], [10])[0], 7)
        self.assertEqual(L.calcular_intervalo([0.6], [10])[0], 4)
        self.assertEqual(L.calcular_intervalo([0.3], [10])[0], 1)
        # "Quero confirmar bem" (3, 7, 15): bom 3, médio 2, mal 1
        degraus = L.tetos_da_fase("degraus")
        self.assertEqual([L.calcular_intervalo([p], [10], tetos=degraus)[0] for p in (1.0, 0.6, 0.3)], [3, 2, 1])

    def test_vale_em_cada_degrau(self):
        # 2ª prática no Equilíbrio (teto 15): médio -> 8
        self.assertEqual(L.calcular_intervalo([1.0, 0.7], [10, 10])[0], 8)

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
        self.assertEqual(L.calcular_intervalo([0.3], [10], teto=30)[0], 1)


class TestRitmo(unittest.TestCase):
    def test_fatores(self):
        self.assertEqual(L.fator_do_ritmo("leve"), 1.0)
        self.assertEqual(L.fator_do_ritmo("moderado"), 0.75)
        self.assertEqual(L.fator_do_ritmo("intenso"), 0.5)
        self.assertEqual(L.fator_do_ritmo(None), 1.0)

    def test_tabela_em_cada_ritmo(self):
        tabela = [3, 4, 7, 15, 30]
        self.assertEqual([L.aplicar_ritmo(d, 0.75) for d in tabela], [2, 3, 5, 11, 22])
        self.assertEqual([L.aplicar_ritmo(d, 0.5) for d in tabela], [1, 2, 3, 7, 15])

    def test_ritmo_vale_para_o_bonus(self):
        base = L.calcular_intervalo([1.0] * 4, [5] * 4)[0]          # 60
        self.assertEqual(L.calcular_intervalo([1.0] * 4, [5] * 4, fator=0.5)[0], base // 2)

    def test_estado_usa_fator(self):
        d = HOJE - timedelta(days=1)
        e = L.analisar_assunto(1, [(d, 10, 10)], HOJE, fator=0.5)
        self.assertEqual(e.intervalo, 3)          # teto 7 x 0,5 = 3,5 -> 3



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


class TestCiclo(unittest.TestCase):
    def itens(self, *rodadas, ultimo=None):
        return [{"id": i, "materia_id": i, "posicao": i, "rodada": r, "ultimo_dia": (ultimo or {}).get(i)}
                for i, r in enumerate(rodadas)]

    def ids(self, lista):
        return [it["id"] for it in lista]

    def test_comeca_pelo_inicio_da_fila(self):
        self.assertEqual(self.ids(L.secoes_da_vez(self.itens(0, 0, 0, 0), 2, HOJE)), [0, 1])

    def test_feito_hoje_continua_na_vez_ate_o_fim_do_dia(self):
        itens = self.itens(1, 0, 0, 0, ultimo={0: HOJE})
        self.assertEqual(self.ids(L.secoes_da_vez(itens, 2, HOJE)), [0, 1])
        # no dia seguinte a fila anda
        self.assertEqual(self.ids(L.secoes_da_vez(itens, 2, HOJE + timedelta(days=1))), [1, 2])

    def test_so_avanca_o_que_foi_feito(self):
        # estudou só a 2ª seção da vez: a 1ª continua na frente
        itens = self.itens(0, 1, 0, 0, ultimo={1: HOJE - timedelta(days=1)})
        self.assertEqual(self.ids(L.secoes_da_vez(itens, 2, HOJE)), [0, 2])

    def test_sem_estudar_a_fila_espera(self):
        itens = self.itens(0, 0, 0)
        self.assertEqual(self.ids(L.secoes_da_vez(itens, 2, HOJE + timedelta(days=5))), [0, 1])

    def test_folga(self):
        self.assertEqual(L.folga_do_ciclo(6, 2), 2)
        self.assertEqual(L.folga_do_ciclo(2, 2), 0)
        self.assertEqual(L.folga_do_ciclo(0, 2), 0)

    def test_folga_nao_conta_como_atraso(self):
        d = HOJE - timedelta(days=6)              # 50% -> volta em 4 dias -> venceu há 2
        self.assertEqual(L.analisar_assunto(1, [(d, 5, 10)], HOJE).atraso, 2)
        self.assertEqual(L.analisar_assunto(1, [(d, 5, 10)], HOJE, folga=2).atraso, 0)


class TestMapa(unittest.TestCase):
    def test_classificacao(self):
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.9, 0.1, HOJE), HOJE), "agora")
        futuro = HOJE + timedelta(days=3)
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.9, 0.1, futuro), HOJE), "dominado")
        self.assertEqual(L.classificar_para_mapa(estado(1, 0.6, 0.4, futuro), HOJE), "esperar")


class TestMeta(unittest.TestCase):
    def test_limite_metade_dos_dias(self):
        self.assertEqual(L.limite_pela_meta(HOJE, HOJE + timedelta(days=60)), 30)
        self.assertEqual(L.limite_pela_meta(HOJE, HOJE + timedelta(days=14)), 7)
        self.assertEqual(L.limite_pela_meta(HOJE, HOJE + timedelta(days=1)), 1)
        self.assertIsNone(L.limite_pela_meta(HOJE, HOJE))          # prova hoje/passada: sem limite
        self.assertIsNone(L.limite_pela_meta(HOJE, None))

    def test_revisao_nunca_passa_da_prova(self):
        # 100% com teto livre iria para 7 dias (fase padrão); a 6 dias da prova volta em 3
        sess = [(HOJE, 10, 10)]
        sem = L.analisar_assunto(1, sess, HOJE)
        com = L.analisar_assunto(1, sess, HOJE, meta=HOJE + timedelta(days=6))
        self.assertEqual(sem.intervalo, 7)
        self.assertEqual(com.intervalo, 3)
        self.assertLess(com.proxima_revisao, HOJE + timedelta(days=6))
        # prova longe: não muda nada
        longe = L.analisar_assunto(1, sess, HOJE, meta=HOJE + timedelta(days=300))
        self.assertEqual(longe.intervalo, 7)

    def test_plano_ritmo_de_assuntos_novos(self):
        meta = HOJE + timedelta(days=100)        # margem = 20 dias -> conteúdo até o dia 80
        p = L.plano_da_meta(HOJE, meta, 20, 0)
        self.assertEqual(p["fim_conteudo"], HOJE + timedelta(days=80))
        self.assertEqual(p["por_semana"], 2)     # 20 assuntos em 80 dias = 1,75 -> 2
        self.assertEqual(p["status"], "abaixo")
        self.assertEqual(L.plano_da_meta(HOJE, meta, 20, 2)["status"], "em_dia")
        self.assertEqual(L.plano_da_meta(HOJE, meta, 0, 0)["status"], "concluido")
        self.assertFalse(p["reta_final"])

    def test_plano_margem_limitada(self):
        # prova em 1 ano: margem de no máximo 60 dias; prova em 10 dias: no mínimo 7
        self.assertEqual(L.margem_de_revisao(365), 60)
        self.assertEqual(L.margem_de_revisao(10), 7)

    def test_plano_atrasado_reta_final_e_passou(self):
        p = L.plano_da_meta(HOJE, HOJE + timedelta(days=5), 3, 0)
        self.assertEqual(p["status"], "atrasado")
        self.assertTrue(p["reta_final"])
        self.assertEqual(L.plano_da_meta(HOJE, HOJE - timedelta(days=1), 3, 0)["status"], "passou")


class TestFlashcards(unittest.TestCase):
    """Cartões seguem a mesma lógica dos assuntos (errei 0%, demorei 75%, acertei 100%)."""

    def agenda(self, *notas, **kw):
        respostas = [(HOJE + timedelta(days=i), n) for i, n in enumerate(notas)]
        return L.agenda_cartao(respostas, **kw)

    def test_cartao_novo(self):
        self.assertIsNone(L.agenda_cartao([]))

    def test_fase_de_aprendizado(self):
        # fase padrão: acertou -> 7 dias; depois 15
        self.assertEqual(self.agenda("acertei")[1], 7)
        self.assertEqual(self.agenda("acertei", "acertei")[1], 15)
        # demorei = resultado médio -> metade do degrau; errei -> 1 dia
        self.assertEqual(self.agenda("demorei")[1], 4)
        self.assertEqual(self.agenda("errei")[1], 1)

    def test_depois_da_fase_usa_a_tabela(self):
        # 7 -> 15 -> 30 (dobra) -> 60
        self.assertEqual(self.agenda("acertei", "acertei", "acertei")[1], 30)
        self.assertEqual(self.agenda("acertei", "acertei", "acertei", "acertei")[1], 60)
        # errou depois de saber: o domínio cai e volta mais cedo
        self.assertLess(self.agenda("acertei", "acertei", "acertei", "errei")[1], 15)

    def test_so_a_primeira_resposta_do_dia_conta(self):
        # errou e depois acertou no mesmo dia (reaprendizado): vale o "errei" -> 1 dia
        mesmo_dia = [(HOJE, "errei"), (HOJE, "acertei")]
        self.assertEqual(L.agenda_cartao(mesmo_dia)[1], 1)
        self.assertEqual(L.agenda_cartao([(HOJE, "errei")])[1], 1)

    def test_ritmo_teto_e_prova(self):
        self.assertEqual(self.agenda("acertei", fator=0.5)[1], 3)          # 7 x 0,5 = 3,5 -> 3 (meio para baixo)
        self.assertEqual(self.agenda("acertei", "acertei", "acertei", "acertei", teto=45)[1], 45)
        ultima = HOJE + timedelta(days=2)
        proxima, dias = self.agenda("acertei", "acertei", "acertei", meta=ultima + timedelta(days=10))
        self.assertEqual(dias, 5)
        self.assertEqual(proxima, ultima + timedelta(days=5))


class TestMesmoDia(unittest.TestCase):
    def test_praticas_do_mesmo_dia_somam(self):
        self.assertEqual(L.juntar_por_dia([(HOJE, 5, 5), (HOJE, 3, 5), (HOJE - timedelta(days=3), 2, 4)]),
                         [(HOJE - timedelta(days=3), 2, 4), (HOJE, 8, 10)])

    def test_conta_como_uma_pratica_so(self):
        separado = L.analisar_assunto(1, [(HOJE, 5, 5), (HOJE, 3, 5)], HOJE)
        junto = L.analisar_assunto(1, [(HOJE, 8, 10)], HOJE)
        self.assertEqual(separado.n_sessoes, 1)
        self.assertEqual((separado.dominio, separado.intervalo), (junto.dominio, junto.intervalo))


class TestPassoPeloTamanho(unittest.TestCase):
    """O intervalo anda na proporção das questões feitas em relação às sugeridas."""

    def seq(self, total, fixas=None, n=6):
        f = L.tetos_da_fase("degraus")
        return [L.calcular_intervalo([1.0] * k, [total] * k, fixas, tetos=f, teto=30)[0] for k in range(1, n + 1)]

    def test_questoes_sugeridas_andam_o_passo_inteiro(self):
        self.assertEqual(self.seq(10), [3, 7, 15, 30, 30, 30])
        self.assertEqual(self.seq(5, fixas=5), [3, 7, 15, 30, 30, 30])   # escolheu 5 fixas: 5 é o passo inteiro

    def test_menos_questoes_andam_menos(self):
        self.assertEqual(self.seq(5)[0], 2)                  # assunto novo pede 10: 5 anda metade (1 -> 3)
        self.assertEqual(self.seq(2, fixas=5), [2, 4, 8, 17, 24, 30])

    def test_peso_do_passo(self):
        self.assertEqual(L.peso_do_passo(5, 10), 0.5)
        self.assertEqual(L.peso_do_passo(5, 4), 1.0)
        self.assertEqual(L.peso_do_passo(5, 20), 0.5)         # referência máxima: 10
        self.assertEqual(L.peso_do_passo(None, 10), 1.0)


if __name__ == "__main__":
    unittest.main()
