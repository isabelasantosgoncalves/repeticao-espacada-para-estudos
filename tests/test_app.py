"""Testes das rotas: autenticação, isolamento entre usuários e validações."""

import os
import re
import tempfile
import unittest

from app import create_app


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
        self.assertIn("Nenhuma sessão ainda", html)

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
        ONTEM = (date.today() - timedelta(days=1)).isoformat()
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
        self.assertIn("vence hoje ou está atrasado", self.c.get("/hoje").get_data(as_text=True))

    def test_dias_de_estudo_da_secao(self):
        from datetime import date, timedelta
        hoje = date.today()
        self.criar_usuario("d@d.com")
        self.post("/configuracoes", {"ritmo": "leve", "aprendizado": "padrao", "teto_dias": "45",
                                     "modo": "completa", "revisao_minima": "2", "questoes_modo": "auto",
                                     "questoes_fixas": "10"}, "/configuracoes")
        self.post("/materias/nova", {"nome": "Música"}, "/materias")
        self.post("/assuntos/novo", {"nome": "Intervalos", "materia_id": "1"}, "/materias")
        # sessão ruim há 10 dias: vencida, entraria na revisão de hoje
        self.post("/sessoes/nova", {"assunto_id": "1", "data": (hoje - timedelta(days=10)).isoformat(),
                                    "acertos": "2", "total": "10"}, "/sessoes/nova")
        self.assertIn("Intervalos", self.c.get("/hoje").get_data(as_text=True).split("Próximos 7 dias")[0])
        # a seção passa a ser estudada só em um dia que não é hoje
        outro_dia = str((hoje.weekday() + 1) % 7)
        self.post("/materias/1/editar", {"nome": "Música", "frequencia": "dias", "dias_estudo": outro_dia},
                  "/materias")
        html = self.c.get("/hoje").get_data(as_text=True)
        self.assertIn("Hoje não é dia de: Música", html)
        self.assertNotIn("Intervalos", html.split("Próximos 7 dias")[0])
        # exportar leva os dias da seção
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"][0]["dias_estudo"],
                         [int(outro_dia)])
        # "só em alguns dias" sem nenhum dia marcado é recusado
        self.post("/materias/1/editar", {"nome": "Música", "frequencia": "dias"}, "/materias")
        self.assertEqual(self.c.get("/configuracoes/exportar").get_json()["materias"][0]["dias_estudo"],
                         [int(outro_dia)])

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
