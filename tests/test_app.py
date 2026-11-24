"""Testes das rotas: autenticação, isolamento entre usuários e validações."""

import os
import re
import tempfile
import unittest

from app import create_app
import servicos as S  # "hoje" no fuso do app (o servidor pode estar em UTC)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE": os.path.join(self.tmp.name, "teste.db"),
            "SECRET_KEY": "teste",
        })
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # -- auxiliares ---------------------------------------------------------

    def token(self, url="/entrar"):
        html = self.c.get(url).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, url, dados, origem="/hoje"):
        dados = dict(dados, csrf_token=self.token(origem))
        return self.c.post(url, data=dados)

    def criar_usuario(self, email):
        tok = self.token("/cadastro")
        self.c.post("/cadastro", data={"nome": "Teste", "email": email, "senha": "segredo1", "csrf_token": tok})
        self.c.post("/onboarding", data={
            "csrf_token": self.token("/onboarding"), "modo": "ambos", "dias_fixos": ["6"],
            "revisao_minima": "2", "questoes_modo": "auto", "questoes_fixas": "10"})

    def sair(self):
        self.c.post("/sair", data={"csrf_token": self.token("/hoje")})

    # -- testes -------------------------------------------------------------

    def test_rotas_exigem_login(self):
        for url in ("/hoje", "/mapa", "/materias", "/configuracoes", "/sessoes/nova"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/entrar", r.headers["Location"])

    def test_post_sem_csrf_e_recusado(self):
        r = self.c.post("/entrar", data={"email": "a@a.com", "senha": "x"})
        self.assertEqual(r.status_code, 400)

    def test_onboarding_obrigatorio(self):
        tok = self.token("/cadastro")
        self.c.post("/cadastro", data={"nome": "N", "email": "n@n.com", "senha": "segredo1", "csrf_token": tok})
        r = self.c.get("/hoje")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/onboarding", r.headers["Location"])

    def test_isolamento_entre_usuarios(self):
        self.criar_usuario("a@a.com")
        self.post("/materias/nova", {"nome": "Física"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Cinemática", "materia_id": "1"}, "/materias")
        self.post("/sessoes/nova", {"assunto_id": "1", "data": "2026-01-10", "acertos": "5", "total": "10"},
                  "/sessoes/nova")
        self.assertEqual(self.c.get("/assuntos/1").status_code, 200)
        self.sair()

        self.criar_usuario("b@b.com")
        self.assertEqual(self.c.get("/assuntos/1").status_code, 404)
        self.assertEqual(self.c.get("/sessoes/1/editar").status_code, 404)
        self.assertEqual(self.post("/assuntos/1/excluir", {}, "/materias").status_code, 404)
        self.assertEqual(self.post("/materias/1/editar", {"nome": "Hack"}, "/materias").status_code, 404)
        # não pode criar assunto em matéria alheia nem sessão em assunto alheio
        self.assertEqual(self.post("/assuntos/novo", {"nome": "X", "materia_id": "1"}, "/materias").status_code, 404)
        r = self.post("/sessoes/nova", {"assunto_id": "1", "data": "2026-01-10", "acertos": "1", "total": "2"},
                      "/sessoes/nova")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("Física", self.c.get("/materias").get_data(as_text=True))

    def test_validacao_acertos_total(self):
        self.criar_usuario("v@v.com")
        self.post("/materias/nova", {"nome": "Química"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Estequiometria", "materia_id": "1"}, "/materias")
        for acertos, total in (("11", "10"), ("1", "0"), ("-1", "5"), ("a", "5")):
            r = self.post("/sessoes/nova", {"assunto_id": "1", "data": "2026-01-10",
                                            "acertos": acertos, "total": total}, "/sessoes/nova")
            self.assertEqual(r.status_code, 200)  # volta ao formulário com erro
        html = self.c.get("/assuntos/1").get_data(as_text=True)
        self.assertIn("Nenhuma prática ainda", html)

    def test_exportar_e_importar(self):
        self.criar_usuario("e@e.com")
        self.post("/materias/nova", {"nome": "Inglês"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Phrasal verbs", "materia_id": "1"}, "/materias")
        self.post("/sessoes/nova", {"assunto_id": "1", "data": "2026-01-10", "acertos": "8", "total": "10",
                                    "observacao": "ok"}, "/sessoes/nova")
        dados = self.c.get("/configuracoes/exportar").get_json()
        self.assertEqual(dados["materias"][0]["assuntos"][0]["sessoes"][0]["acertos"], 8)

        import io, json
        self.post("/materias/nova", {"nome": "Temporária"}, "/materias")
        arquivo = (io.BytesIO(json.dumps(dados).encode()), "backup.json")
        self.c.post("/configuracoes/importar", data={
            "csrf_token": self.token("/configuracoes"), "confirmar": "1", "arquivo": arquivo},
            content_type="multipart/form-data")
        html = self.c.get("/materias").get_data(as_text=True)
        self.assertIn("Inglês", html)
        self.assertNotIn("Temporária", html)

    def test_subassuntos(self):
        from datetime import date, timedelta
        ONTEM = (S.hoje() - timedelta(days=1)).isoformat()
        self.criar_usuario("s@s.com")
        self.post("/materias/nova", {"nome": "SAT Math"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Algebra", "materia_id": "1"}, "/materias")       # id 1
        self.post("/assuntos/novo", {"nome": "Equations", "parent_id": "1"}, "/materias")      # id 2
        self.post("/assuntos/novo", {"nome": "Inequalities", "parent_id": "1"}, "/materias")   # id 3
        # subassunto de subassunto não é permitido
        self.post("/assuntos/novo", {"nome": "Profundo", "parent_id": "2"}, "/materias")
        self.assertNotIn("Profundo", self.c.get("/materias").get_data(as_text=True))
        # o grupo não recebe sessão; o subassunto recebe
        r = self.post("/sessoes/nova", {"assunto_id": "1", "data": ONTEM, "acertos": "5", "total": "10"},
                      "/sessoes/nova")
        self.assertIn("subassuntos", r.get_data(as_text=True))
        self.post("/sessoes/nova", {"assunto_id": "2", "data": ONTEM, "acertos": "9", "total": "10"},
                  "/sessoes/nova")
        self.post("/sessoes/nova", {"assunto_id": "3", "data": ONTEM, "acertos": "3", "total": "10"},
                  "/sessoes/nova")
        html = self.c.get("/assuntos/1").get_data(as_text=True)
        self.assertIn("60%", html)            # média de 90% e 30%
        mapa = self.c.get("/mapa").get_data(as_text=True)
        self.assertIn("Inequalities", mapa)
        # exportar e importar preserva a hierarquia
        dados = self.c.get("/configuracoes/exportar").get_json()
        subs = dados["materias"][0]["assuntos"][0]["subassuntos"]
        self.assertEqual([x["nome"] for x in subs], ["Equations", "Inequalities"])
        import io, json
        self.c.post("/configuracoes/importar", data={
            "csrf_token": self.token("/configuracoes"), "confirmar": "1",
            "arquivo": (io.BytesIO(json.dumps(dados).encode()), "b.json")}, content_type="multipart/form-data")
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"], dados["materias"])
        # excluir o pai remove os subassuntos
        self.post("/assuntos/4/excluir", {}, "/materias")
        self.assertNotIn("Inequalities", self.c.get("/materias").get_data(as_text=True))

    def test_subassunto_em_assunto_alheio(self):
        self.criar_usuario("a@a.com")
        self.post("/materias/nova", {"nome": "Bio"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Citologia", "materia_id": "1"}, "/materias")
        self.sair()
        self.criar_usuario("b@b.com")
        r = self.post("/assuntos/novo", {"nome": "Intruso", "parent_id": "1"}, "/materias")
        self.assertEqual(r.status_code, 404)

    def test_modo_completa_nao_exige_dia_fixo(self):
        self.criar_usuario("c@c.com")
        self.c.post("/configuracoes", data={
            "csrf_token": self.token("/configuracoes"), "ritmo": "intenso", "aprendizado": "padrao",
            "modo": "completa", "revisao_minima": "2", "questoes_modo": "auto", "questoes_fixas": "10"})
        cfg = self.c.get("/configuracoes/exportar").get_json()["configuracoes"]
        self.assertEqual(cfg["modo"], "completa")
        self.post("/materias/nova", {"nome": "Math"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Algebra", "materia_id": "1"}, "/materias")
        self.assertIn("Tudo que venceu", self.c.get("/hoje").get_data(as_text=True))

    def test_dias_de_estudo_da_secao(self):
        from datetime import date, timedelta
        hoje = S.hoje()
        self.criar_usuario("d@d.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "distribuicao": "dias", "modo": "completa", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "Música"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Intervalos", "materia_id": "1"}, "/materias")
        # sessão ruim há 10 dias: vencida, entraria na revisão de hoje
        self.post("/sessoes/nova", {"assunto_id": "1", "data": (hoje - timedelta(days=10)).isoformat(),
                                    "acertos": "2", "total": "10"}, "/sessoes/nova")
        self.assertIn("Intervalos", self.c.get("/hoje").get_data(as_text=True).split('<aside class="lateral">')[0])
        # a seção passa a ser estudada só em um dia que não é hoje
        outro_dia = str((hoje.weekday() + 1) % 7)
        self.post("/materias/1/editar", {"nome": "Música", "frequencia": "dias", "dias_estudo": outro_dia},
                  "/materias")
        html = self.c.get("/hoje").get_data(as_text=True)
        self.assertIn("fora hoje: Música", html)
        self.assertNotIn("Intervalos", html.split('<aside class="lateral">')[0])
        # exportar leva os dias da seção
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"][0]["dias_estudo"],
                         [int(outro_dia)])
        # "só em alguns dias" sem nenhum dia marcado é recusado
        self.post("/materias/1/editar", {"nome": "Música", "frequencia": "dias"}, "/materias")
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"][0]["dias_estudo"],
                         [int(outro_dia)])

    def test_dia_sem_vencimento_e_mapa_sem_nao_estudados(self):
        hoje = S.hoje()
        from datetime import timedelta
        self.criar_usuario("v@z.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "modo": "diaria", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "SAT"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Algebra", "materia_id": "1"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Geometria", "materia_id": "1"}, "/materias")
        # acertou tudo ontem: só volta em 7 dias, então hoje não há revisão
        self.post("/sessoes/nova", {"assunto_id": "1", "data": (hoje - timedelta(days=1)).isoformat(),
                                    "acertos": "10", "total": "10"}, "/sessoes/nova")
        html = self.c.get("/hoje").get_data(as_text=True).split('<aside class="lateral">')[0]
        self.assertNotIn("Algebra", html)
        # mapa: só estudados, sem a lista de "ainda não estudados"
        mapa = self.c.get("/mapa").get_data(as_text=True)
        self.assertIn("Algebra", mapa)
        self.assertNotIn("Geometria", mapa)
        self.assertIn("1 assunto ainda não começado", mapa)

    def test_previa_de_amanha(self):
        hoje = S.hoje()
        self.criar_usuario("am@am.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "degraus", "teto_dias": "30",
                                     "modo": "diaria", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "SAT"}, "/materias")
        for nome in ("Alfa", "Beta", "Gama"):
            self.post("/assuntos/novo", {"nome": nome, "materia_id": "1"}, "/materias")
        # três assuntos começados hoje: 100%, 40%, 60%
        for aid, ac in (("1", "10"), ("2", "4"), ("3", "6")):
            self.post("/sessoes/nova", {"assunto_id": aid, "data": hoje.isoformat(),
                                        "acertos": ac, "total": "10"}, "/sessoes/nova")
        html = self.c.get("/hoje").get_data(as_text=True)
        amanha = html.split('class="bloco amanha"')[1].split("</section>")[0]
        self.assertIn("Beta", amanha)      # 40%: foi mal, volta em 1 dia
        self.assertNotIn("Gama", amanha)   # 60%: médio, volta em 2 dias
        self.assertNotIn("Alfa", amanha)   # 100%: bom, volta em 3 dias
        self.assertIn("Próximas revisões", html)

    def test_ciclo_de_estudos(self):
        hoje = S.hoje()
        self.criar_usuario("ci@ci.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "distribuicao": "ciclo", "secoes_por_dia": "2", "modo": "diaria",
                                     "revisao_minima": "2", "questoes_modo": "auto", "questoes_fixas": "10"},
                  "/configuracoes")
        for nome in ("Matemática", "Biologia", "História"):
            self.post("/materias/nova", {"nome": nome}, "/materias")
        for mid in ("1", "2", "3"):
            self.post("/ciclo/adicionar", {"materia_id": mid}, "/materias")
        self.post("/assuntos/novo", {"nome": "Funções", "materia_id": "1"}, "/materias")

        def vez():
            html = self.c.get("/hoje").get_data(as_text=True)
            bloco = html.split('class="vez-hoje"')[1].split("</div>")[0]
            return [n for n in ("Matemática", "Biologia", "História") if n in bloco], bloco

        nomes, _ = vez()
        self.assertEqual(nomes, ["Matemática", "Biologia"])
        # praticou Matemática hoje: continua na vez (com ✓) e amanhã vêm Biologia e História
        self.post("/sessoes/nova", {"assunto_id": "1", "data": hoje.isoformat(), "acertos": "8", "total": "10"},
                  "/sessoes/nova")
        nomes, bloco = vez()
        self.assertEqual(nomes, ["Matemática", "Biologia"])
        self.assertIn("✓", bloco)
        html = self.c.get("/hoje").get_data(as_text=True)
        amanha = html.split('class="bloco amanha"')[1].split("</section>")[0]
        self.assertIn("Matérias: Biologia, História", amanha)
        # pular Biologia: entra História no lugar
        self.post("/ciclo/2/pular", {}, "/hoje")
        nomes, _ = vez()
        self.assertEqual(nomes, ["Matemática", "História"])
        # a fila vai junto no exportar
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["ciclo"],
                         ["Matemática", "Biologia", "História"])

    def test_revisoes_planejadas_respeitam_o_limite(self):
        from datetime import timedelta
        hoje = S.hoje()
        self.criar_usuario("pl@pl.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "modo": "diaria", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "Math"}, "/materias")
        for nome in ("A1", "A2", "A3"):
            self.post("/assuntos/novo", {"nome": nome, "materia_id": "1"}, "/materias")
        # os três venceram (30% há 5 dias -> voltariam em 1 dia)
        for aid in ("1", "2", "3"):
            self.post("/sessoes/nova", {"assunto_id": aid, "data": (hoje - timedelta(days=5)).isoformat(),
                                        "acertos": "3", "total": "10"}, "/sessoes/nova")
        html = self.c.get("/vencimentos").get_data(as_text=True)
        dias = html.split('class="bloco vc-dia')[1:]
        conta = lambda bloco: sum(bloco.count(f">{n}<") for n in ("A1", "A2", "A3"))
        self.assertEqual(conta(dias[0]), 2)   # hoje: o limite de 2
        self.assertEqual(conta(dias[1]), 1)   # amanhã: o que não coube

    def test_secao_com_prova(self):
        from datetime import timedelta
        hoje = S.hoje()
        self.criar_usuario("meta@m.com")
        # seção ENEM com prova daqui a 10 dias; Inglês fica solta, sem prova
        prova = hoje + timedelta(days=10)
        self.post("/secoes/nova", {"nome": "ENEM", "meta_tipo": "dia", "meta_dia": prova.isoformat()}, "/materias")
        self.post("/materias/nova", {"nome": "Matemática", "secao_id": "1"}, "/materias")
        self.post("/materias/nova", {"nome": "Biologia", "secao_id": "1"}, "/materias")
        self.post("/materias/nova", {"nome": "Inglês"}, "/materias")
        for nome, mid in (("Funções", "1"), ("Citologia", "2"), ("Vocabulário", "3")):
            self.post("/assuntos/novo", {"nome": nome, "materia_id": mid}, "/materias")
        pagina = self.c.get("/materias").get_data(as_text=True)
        self.assertIn("ENEM", pagina)
        self.assertIn("Sem seção", pagina)
        self.post("/sessoes/nova", {"assunto_id": "1", "data": hoje.isoformat(), "acertos": "10", "total": "10"},
                  "/sessoes/nova")
        self.post("/sessoes/nova", {"assunto_id": "3", "data": hoje.isoformat(), "acertos": "10", "total": "10"},
                  "/sessoes/nova")
        html = self.c.get("/hoje").get_data(as_text=True)
        metas = html.split('kpi-prova')[1].split('<div class="painel-grade">')[0]
        self.assertIn("ENEM", metas)
        self.assertNotIn("Inglês", metas)
        self.assertIn("1 de 2 assuntos começados", metas)   # as duas matérias do ENEM contam juntas
        self.assertIn("Reta final", metas)
        # intervalo limitado pela prova (10 dias -> até 5) só nas matérias do ENEM
        import db as banco
        with self.app.app_context():
            cfg = S.carregar_config(banco.get_db(), 1)
            est = S.estados(banco.get_db(), 1, hoje, cfg)
        self.assertEqual(est[1].intervalo, 5)
        self.assertEqual(est[3].intervalo, 7)
        # Inglês entra no ENEM: passa a seguir a prova
        self.post("/materias/3/editar", {"nome": "Inglês", "secao_id": "1"}, "/materias")
        with self.app.app_context():
            est = S.estados(banco.get_db(), 1, hoje, S.carregar_config(banco.get_db(), 1))
        self.assertEqual(est[3].intervalo, 5)
        # tirar a prova da seção
        self.post("/secoes/1/editar", {"nome": "ENEM", "meta_tipo": "sem"}, "/materias")
        self.assertNotIn('kpi-prova', self.c.get("/hoje").get_data(as_text=True))
        # excluir a seção mantém as matérias
        self.post("/secoes/1/excluir", {}, "/materias")
        self.assertEqual(len(self.c.get("/configuracoes/exportar").get_json()["materias"]), 3)

    def test_fazer_mais_hoje_quando_atrasado(self):
        from datetime import timedelta
        hoje = S.hoje()
        self.criar_usuario("mais@m.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "modo": "diaria", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "SAT"}, "/materias")
        nomes = ("Alfa", "Beta", "Gama", "Delta", "Épsilon")
        for i, nome in enumerate(nomes, 1):
            self.post("/assuntos/novo", {"nome": nome, "materia_id": "1"}, "/materias")
            # todos vencidos (foram mal há 10 dias)
            self.post("/sessoes/nova", {"assunto_id": str(i), "data": (hoje - timedelta(days=10)).isoformat(),
                                        "acertos": "2", "total": "10"}, "/sessoes/nova")

        def lista():
            html = self.c.get("/hoje").get_data(as_text=True)
            return html.split('<aside class="lateral">')[0]

        def na_lista(html):
            return sum(1 for n in nomes if f">{n}</a>" in html)

        html = lista()
        self.assertEqual(na_lista(html), 2)                  # limite de 2 por seção
        self.assertIn("3 revisões atrasadas", html)
        self.post("/hoje/mais", {"quantos": "2"})
        html = lista()
        self.assertEqual(na_lista(html), 4)
        self.assertIn("a mais", html)
        self.assertIn("1 revisão atrasada", html)
        self.post("/hoje/mais", {"quantos": "todas"})
        html = lista()
        self.assertEqual(na_lista(html), 5)
        self.assertNotIn('class="mais-hoje"', html)

    def test_sem_atraso_nao_oferece_fazer_mais(self):
        hoje = S.hoje()
        self.criar_usuario("sem@m.com")
        self.post("/materias/nova", {"nome": "SAT"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Alfa", "materia_id": "1"}, "/materias")
        self.post("/sessoes/nova", {"assunto_id": "1", "data": hoje.isoformat(), "acertos": "10", "total": "10"},
                  "/sessoes/nova")
        self.assertNotIn('class="mais-hoje"', self.c.get("/hoje").get_data(as_text=True))

    def test_prova_so_com_o_mes_e_exportar(self):
        from datetime import date
        hoje = S.hoje()
        self.criar_usuario("conta@m.com")
        # "sei só o mês" sem escolher o mês é recusado
        self.post("/secoes/nova", {"nome": "ENEM", "meta_tipo": "mes", "meta_mes": ""}, "/materias")
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["secoes"], [])
        mes = f"{hoje.year + 1}-11"
        self.post("/secoes/nova", {"nome": "ENEM", "meta_tipo": "mes", "meta_mes": mes}, "/materias")
        self.post("/secoes/nova", {"nome": "Música"}, "/materias")
        self.post("/materias/nova", {"nome": "Matemática", "secao_id": "1"}, "/materias")
        self.post("/materias/nova", {"nome": "Teoria musical", "secao_id": "2"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Funções", "materia_id": "1"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Escalas", "materia_id": "2"}, "/materias")
        html = self.c.get("/hoje").get_data(as_text=True)
        metas = html.split('kpi-prova')[1].split('<div class="painel-grade">')[0]
        self.assertIn(f"nov/{hoje.year + 1}", metas)
        self.assertNotIn("Música", metas)
        faltam = (date(hoje.year + 1, 11, 1) - hoje).days
        self.assertIn(f"~<strong>{faltam}</strong>", metas)
        # Configurações muda a prova de cada seção
        base = {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45", "modo": "diaria",
                "revisao_minima": "2", "questoes_modo": "auto", "questoes_fixas": "10"}
        self.post("/configuracoes", dict(base, meta_1_tipo="dia", meta_1_dia=f"{hoje.year + 1}-11-07",
                                         meta_2_tipo="sem"), "/configuracoes")
        dados = self.c.get("/configuracoes/exportar").get_json()
        self.assertEqual(dados["secoes"], [{"nome": "ENEM", "data_meta": f"{hoje.year + 1}-11-07"}, {"nome": "Música"}])
        self.assertEqual(dados["materias"][0]["secao"], "ENEM")
        # importar recria as seções e liga as matérias
        import io, json
        self.post("/configuracoes/importar", {"arquivo": (io.BytesIO(json.dumps(dados).encode()), "b.json"),
                                              "confirmar": "1"}, "/configuracoes")
        de_novo = self.c.get("/configuracoes/exportar").get_json()
        self.assertEqual(de_novo["secoes"], dados["secoes"])
        self.assertEqual([m.get("secao") for m in de_novo["materias"]], ["ENEM", "Música"])

    def test_onboarding_pergunta_a_prova(self):
        tok = self.token("/cadastro")
        self.c.post("/cadastro", data={"nome": "N", "email": "ob@ob.com", "senha": "segredo1", "csrf_token": tok})
        html = self.c.get("/onboarding").get_data(as_text=True)
        self.assertIn("prova com data", html)
        self.c.post("/onboarding", data={
            "csrf_token": self.token("/onboarding"), "modo": "completa", "revisao_minima": "2",
            "questoes_modo": "auto", "questoes_fixas": "10", "meta_tipo": "mes", "meta_mes": "2027-11",
            "prova_nome": "ENEM"})
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["secoes"],
                         [{"nome": "ENEM", "data_meta": "2027-11"}])

    def test_flashcards(self):
        self.criar_usuario("fc@fc.com")
        self.post("/materias/nova", {"nome": "SAT Math"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Linear", "materia_id": "1"}, "/materias")
        self.post("/flashcards/baralhos/novo", {"nome": "Fórmulas", "materia_id": "1"}, "/flashcards")
        self.post("/flashcards/baralhos/1/cartoes", {"frente": "Bhaskara", "verso": "x = (-b ± √Δ)/2a"}, "/flashcards")
        # vários de uma vez: TAB (planilha) ou " | "
        self.post("/flashcards/baralhos/1/cartoes", {"lote": "Δ\tb² - 4ac\nÁrea do círculo | πr²\n\n"}, "/flashcards")
        html = self.c.get("/flashcards/baralhos/1").get_data(as_text=True)
        self.assertIn("3 cartões", html)
        self.assertIn("πr²", html)
        # linha sem separador é recusada (nada é gravado)
        self.post("/flashcards/baralhos/1/cartoes", {"lote": "sem separador"}, "/flashcards")
        self.assertIn("3 cartões", self.c.get("/flashcards/baralhos/1").get_data(as_text=True))

        # painel mostra os cartões do dia
        self.assertIn("3 para estudar hoje", self.c.get("/hoje").get_data(as_text=True))

        # estudar: 3 botões, sem mostrar dias
        estudo = self.c.get("/flashcards/estudar").get_data(as_text=True)
        self.assertIn("Bhaskara", estudo)
        self.assertIn("Acertei, mas demorei", estudo)
        self.assertNotIn(" dias<", estudo)
        for cid, nota in (("1", "errei"), ("2", "demorei"), ("3", "acertei")):
            self.post("/flashcards/responder", {"cartao_id": cid, "nota": nota}, "/flashcards")
        # errou: volta na mesma sessão até acertar (como no Anki)
        estudo = self.c.get("/flashcards/estudar").get_data(as_text=True)
        self.assertIn("Bhaskara", estudo)
        self.assertIn('cont-aprendendo atual', estudo)
        self.post("/flashcards/responder", {"cartao_id": "1", "nota": "acertei"}, "/flashcards")
        self.assertIn("Tudo em dia", self.c.get("/flashcards/estudar").get_data(as_text=True))
        self.assertIn("Nenhum cartão para hoje", self.c.get("/hoje").get_data(as_text=True))
        # resposta inválida é ignorada
        self.post("/flashcards/responder", {"cartao_id": "1", "nota": "facil"}, "/flashcards")

        # agenda com a lógica das questões (fase padrão 7/15, ritmo leve):
        # errei -> 1 dia; demorei (75%) -> metade do degrau = 4; acertei -> 7
        import db as banco
        import cartoes as C
        with self.app.app_context():
            agenda = {c["id"]: c["intervalo"] for c in C.cartoes_com_agenda(banco.get_db(), 1, S.hoje())}
        self.assertEqual(agenda, {1: 1, 2: 4, 3: 7})

        # exportar e importar levam baralhos, cartões e respostas
        import io, json
        dados = self.c.get("/configuracoes/exportar").get_json()
        cartoes = dados["materias"][0]["baralhos"][0]["cartoes"]
        self.assertEqual([c["respostas"][0][1] for c in cartoes], ["errei", "demorei", "acertei"])
        self.assertEqual(len(cartoes[0]["respostas"]), 2)        # errei + acertei no mesmo dia
        self.post("/configuracoes/importar", {"arquivo": (io.BytesIO(json.dumps(dados).encode()), "b.json"),
                                              "confirmar": "1"}, "/configuracoes")
        de_novo = self.c.get("/configuracoes/exportar").get_json()
        self.assertEqual(de_novo["materias"][0]["baralhos"], dados["materias"][0]["baralhos"])

        # outro usuário não acessa o baralho nem responde cartões alheios
        self.sair()
        self.criar_usuario("outro@fc.com")
        self.assertEqual(self.c.get("/flashcards/baralhos/1").status_code, 404)
        self.assertEqual(self.post("/flashcards/responder", {"cartao_id": "4", "nota": "acertei"},
                                   "/flashcards").status_code, 404)

    def test_flashcards_respeitam_a_prova(self):
        from datetime import timedelta
        hoje = S.hoje()
        self.criar_usuario("fp@fc.com")
        self.post("/secoes/nova", {"nome": "ENEM", "meta_tipo": "dia",
                                   "meta_dia": (hoje + timedelta(days=4)).isoformat()}, "/materias")
        self.post("/materias/nova", {"nome": "Matemática", "secao_id": "1"}, "/materias")
        self.post("/flashcards/baralhos/novo", {"nome": "Fórmulas", "materia_id": "1"}, "/flashcards")
        self.post("/flashcards/baralhos/1/cartoes", {"frente": "a", "verso": "b"}, "/flashcards")
        self.post("/flashcards/responder", {"cartao_id": "1", "nota": "acertei"}, "/flashcards")
        # "acertei" daria 7 dias; com a prova em 4 dias, volta em 2 (metade)
        import db as banco
        import cartoes as C
        with self.app.app_context():
            self.assertEqual(C.cartoes_com_agenda(banco.get_db(), 1, S.hoje())[0]["intervalo"], 2)

    def test_flashcards_jeito_anki(self):
        import io
        import db as banco
        import cartoes as C
        hoje = S.hoje()
        self.criar_usuario("anki@fc.com")
        self.post("/materias/nova", {"nome": "Biologia"}, "/materias")
        self.post("/flashcards/baralhos/novo", {"nome": "Organelas", "materia_id": "1"}, "/flashcards")
        # cartão invertido com imagem no verso
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        self.post("/flashcards/baralhos/1/cartoes", {"frente": "Mitocôndria", "verso": "", "invertido": "1",
                                                     "imagem_verso": (io.BytesIO(png), "m.png")}, "/flashcards")
        self.post("/flashcards/baralhos/1/cartoes", {"frente": "Ribossomo", "verso": "Proteínas"}, "/flashcards")
        # arquivo que não é imagem é recusado
        self.post("/flashcards/baralhos/1/cartoes", {"frente": "x", "verso": "y",
                                                     "imagem_frente": (io.BytesIO(b"oi"), "a.png")}, "/flashcards")
        with self.app.app_context():
            lados = C.cartoes_com_agenda(banco.get_db(), 1, hoje)
        self.assertEqual(len(lados), 3)                               # 2 lados + 1
        self.assertEqual(self.c.get("/flashcards/imagens/1").data, png)
        # contadores: 2 novos hoje (o outro lado do invertido espera até amanhã depois de estudado)
        estudo = self.c.get("/flashcards/estudar").get_data(as_text=True)
        self.assertIn('title="Novos">3<', estudo)
        self.post("/flashcards/responder", {"cartao_id": "1", "lado": "0", "nota": "acertei"}, "/flashcards")
        estudo = self.c.get("/flashcards/estudar").get_data(as_text=True)
        self.assertIn('title="Novos">1<', estudo)                    # o irmão invertido ficou para amanhã
        self.assertIn("Ribossomo", estudo)
        # desfazer devolve o cartão
        self.post("/flashcards/desfazer", {}, "/flashcards")
        self.assertIn('title="Novos">3<', self.c.get("/flashcards/estudar").get_data(as_text=True))
        # adiar tira só de hoje; suspender tira até reativar
        self.post("/flashcards/cartoes/2/adiar", {"voltar": "estudo"}, "/flashcards")
        self.post("/flashcards/cartoes/1/suspender", {"voltar": "estudo"}, "/flashcards")
        self.assertIn("Tudo em dia", self.c.get("/flashcards/estudar").get_data(as_text=True))
        self.post("/flashcards/cartoes/1/suspender", {}, "/flashcards")
        self.assertIn("Mitocôndria", self.c.get("/flashcards/estudar").get_data(as_text=True))
        # editar no estudo volta para o estudo e pode tirar a imagem
        r = self.post("/flashcards/cartoes/1/editar", {"frente": "Mitocôndria", "verso": "ATP", "tem_invertido": "1",
                                                       "remover_imagem_verso": "1", "voltar": "estudo"}, "/flashcards")
        self.assertIn("/flashcards/estudar", r.headers["Location"])
        self.assertEqual(self.c.get("/flashcards/imagens/1").status_code, 404)   # imagem solta foi apagada
        # exportar/importar levam invertido e imagem
        self.post("/flashcards/cartoes/1/editar", {"frente": "Mitocôndria", "verso": "ATP", "tem_invertido": "1",
                                                   "invertido": "1", "imagem_frente": (io.BytesIO(png), "m.png")},
                  "/flashcards")
        import json
        dados = self.c.get("/configuracoes/exportar").get_json()
        c1 = dados["materias"][0]["baralhos"][0]["cartoes"][0]
        self.assertTrue(c1["invertido"])
        self.assertTrue(c1["imagem_frente"].startswith("data:image/png;base64,"))
        self.post("/configuracoes/importar", {"arquivo": (io.BytesIO(json.dumps(dados).encode()), "b.json"),
                                              "confirmar": "1"}, "/configuracoes")
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"], dados["materias"])
        # imagem de outro usuário não aparece
        self.sair()
        self.criar_usuario("outro@anki.com")
        self.assertEqual(self.c.get("/flashcards/imagens/3").status_code, 404)

    def test_pwa(self):
        r = self.c.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r.headers["Content-Type"])
        self.assertEqual(r.get_json()["display"], "standalone")
        r = self.c.get("/sw.js")
        self.assertIn("javascript", r.headers["Content-Type"])
        self.assertEqual(self.c.get("/offline").status_code, 200)

    def test_onboarding_salva_ritmo_e_fase(self):
        tok = self.token("/cadastro")
        self.c.post("/cadastro", data={"nome": "N", "email": "r@r.com", "senha": "segredo1", "csrf_token": tok})
        self.c.post("/onboarding", data={
            "csrf_token": self.token("/onboarding"), "ritmo": "intenso", "aprendizado": "degraus",
            "modo": "diaria", "revisao_minima": "3", "questoes_modo": "auto", "questoes_fixas": "10"})
        cfg = self.c.get("/configuracoes/exportar").get_json()["configuracoes"]
        self.assertEqual((cfg["ritmo"], cfg["aprendizado"]), ("intenso", "degraus"))
        self.assertEqual(cfg["teto_dias"], 30)          # sem resposta: usa a sugestão
        self.assertNotIn("(ritmo leve)", self.c.get("/configuracoes").get_data(as_text=True))
        # teto fora do intervalo permitido é recusado
        self.c.post("/configuracoes", data={
            "csrf_token": self.token("/configuracoes"), "ritmo": "intenso", "aprendizado": "degraus",
            "teto_dias": "500", "modo": "diaria", "revisao_minima": "3", "questoes_modo": "auto",
            "questoes_fixas": "10"})
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["configuracoes"]["teto_dias"], 30)
        # valor inválido não é aceito
        self.c.post("/configuracoes", data={
            "csrf_token": self.token("/configuracoes"), "ritmo": "turbo", "aprendizado": "degraus",
            "modo": "diaria", "revisao_minima": "3", "questoes_modo": "auto", "questoes_fixas": "10"})
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["configuracoes"]["ritmo"], "intenso")


if __name__ == "__main__":
    unittest.main()
